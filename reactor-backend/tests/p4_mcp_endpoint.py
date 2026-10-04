"""Real MCP SDK test endpoint (TCP SSE/HTTP and JSON-RPC STDIO)."""
import argparse
from pathlib import Path
import os
from mcp.server.fastmcp import FastMCP


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--transport',choices=['sse','stdio','streamable-http'],required=True);parser.add_argument('--port',type=int,default=0)
    args=parser.parse_args()
    mcp=FastMCP('p4-isolated',host='127.0.0.1',port=args.port)
    @mcp.tool(name='original.echo!')
    def echo(text:str)->dict:
        return {'echo':text,'wire_name':'original.echo!','pid':os.getpid()}
    @mcp.tool(name='always',meta={'anthropic/alwaysLoad':True})
    def always()->str:return 'real MCP response'
    @mcp.resource('p4://manual')
    def manual()->str:return '真实 MCP resource 内容'
    mcp.run(transport=args.transport)


if __name__=='__main__':main()
