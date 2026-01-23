from mcp.server.fastmcp import FastMCP
from generate_weekly_report import generate_weekly_report

# Create MCP server
mcp = FastMCP("weekly-report-server")

@mcp.tool()
def generate_weekly_report_tool():
    """
    Generate weekly Zoho ticket report and return summary.
    """
    return generate_weekly_report()

if __name__ == "__main__":
    mcp.run()
