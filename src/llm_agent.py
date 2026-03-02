import asyncio

from digitalai.release.integration import BaseTask
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from langchain.agents import create_agent
from langchain_mcp_adapters.client import MultiServerMCPClient
import re

from src.llm_prompt import create_model, markdown_quote, format_exception
from src.http_auth import create_auth_headers


class LlmAgent(BaseTask):

    def execute(self) -> None:
        # Get input
        prompt = self.input_properties.get('prompt')
        if prompt is None:
            raise ValueError("Prompt field cannot be empty")
        model = self.input_properties['model']
        if model is None:
            raise ValueError("Model field cannot be empty")
        mcp_servers = {}
        for server in [self.input_properties.get('mcpServer1'), self.input_properties.get('mcpServer2'),
                       self.input_properties.get('mcpServer3')]:
            if server:
                transport = server['transport']
                if transport == 'http':
                    transport = 'streamable_http'

                auth_headers = create_auth_headers(server)

                mcp_servers[server['title']] = {
                    "url": server['url'],
                    "transport": transport,
                    "headers": auth_headers
                }

        # Call agent
        model_connector = create_model(model)
        try:
            output = asyncio.run(send_prompt(prompt, model_connector, mcp_servers))
            print("AgentPrompt Result:\n", output)
        except Exception as e:
            root, error_details = format_exception(e)
            raise RuntimeError(f"Agent execution failed - {error_details}") from root

        report = create_markdown_report(output)
        self.add_comment(report)

        # Process result
        result = last_agent_message(output)
        self.set_output_property('result', result)

        if '🙋🏻' in result:
            raise Exception("Could not complete the task because the agent needs more information.")


async def send_prompt(prompt, model, mcp_servers):
    client = MultiServerMCPClient(mcp_servers)

    tools = []
    server_descriptions = []
    for server_name in mcp_servers:
        server_tools = await client.get_tools(server_name=server_name)
        prefix = re.sub(r"[^\w]+", "_", server_name.lower())
        for tool in server_tools:
            tool_copy = tool.model_copy()
            tool_copy.name = f"{prefix}__{tool.name}"
            tools.append(tool_copy)
        server_descriptions.append(f"- '{server_name}' (tool prefix: '{prefix}__')")

    servers_info = "\n    ".join(server_descriptions)
    system_prompt = f"""
    You are an AI assistant in the DevOps domain and are running inside the Digital.ai Release product as a task.

    You have access to the following MCP servers:
    {servers_info}

    All tool names follow the [server_prefix]__[tool_name] convention. Match the tool's prefix to the specific service required for the task.
    (e.g. 'release_mcp__list_releases' vs 'github_mcp__list_releases').

    If you need more information from the user to complete a task, you must end your response with the 🙋🏻emoji to prompt the user for more information.
    Do not use the 🙋🏻 emoji  in other cases, since it will fail the task and disrupt the release flow.
    """

    agent = create_agent(model=model, tools=tools, system_prompt=system_prompt)

    response = await agent.ainvoke({"messages": prompt})

    return response


def last_agent_message(output):
    return output['messages'][-1].text


def create_markdown_report(output):
    markdown = ''
    for message in output['messages']:
        if isinstance(message, HumanMessage):
            markdown += markdown_quote(message.content)
        if isinstance(message, AIMessage):
            if message.content:
                markdown += f"{message.text}\n\n"
        if isinstance(message, ToolMessage):
            success = message.status == 'success'
            status = "✅" if success else "❌"
            markdown += f"```\n {status} {message.name}\n```\n\n"
            if not success:
                markdown += f"```\n{message.content}\n```\n\n"

    return markdown
