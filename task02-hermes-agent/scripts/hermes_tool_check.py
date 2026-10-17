import json
from tools.terminal_tool import terminal_tool
result=terminal_tool(command="printf 'HERMES_TOOL_OK\\n'",timeout=10,task_id='soulo-preflight')
print(result)
parsed=json.loads(result)
assert 'HERMES_TOOL_OK' in str(parsed), parsed
assert not parsed.get('error'), parsed
print('PASS: actual Hermes terminal implementation executed. No LLM request was made.')
