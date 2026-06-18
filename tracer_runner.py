import sys
import io
import json
import traceback

def serialize_val(v, depth=0):
    if depth > 6:
        return repr(v)
    if isinstance(v, (int, float, str, bool, type(None))):
        return v
    if isinstance(v, list):
        return [serialize_val(x, depth + 1) for x in v]
    if isinstance(v, dict):
        return {str(ki): serialize_val(vi, depth + 1) for ki, vi in v.items()}
    if isinstance(v, (set, tuple)):
        return [serialize_val(x, depth + 1) for x in list(v)]
    if hasattr(v, '__dict__'):
        obj_dict = {}
        for k_field, v_field in v.__dict__.items():
            if not k_field.startswith('_'):
                obj_dict[k_field] = serialize_val(v_field, depth + 1)
        obj_dict['__class__'] = type(v).__name__
        obj_dict['__id__'] = id(v)
        return obj_dict
    return repr(v)

class StepTracer:
    def __init__(self, max_steps=500):
        self.steps = []
        self.stdout_buffer = io.StringIO()
        self.max_steps = max_steps
        self.step_count = 0

    def trace_calls(self, frame, event, arg):
        if self.step_count >= self.max_steps:
            raise RuntimeError("TraceLimitExceeded: Execution stepped too many times (capped at 500 steps).")
        if frame.f_code.co_filename == '<string>':
            self.record_step(frame, event, arg)
        return self.trace_lines

    def trace_lines(self, frame, event, arg):
        if self.step_count >= self.max_steps:
            raise RuntimeError("TraceLimitExceeded: Execution stepped too many times (capped at 500 steps).")
        if frame.f_code.co_filename == '<string>':
            self.record_step(frame, event, arg)
        return self.trace_lines

    def record_step(self, frame, event, arg):
        self.step_count += 1
        lineno = frame.f_lineno
        
        # Capture stack frame hierarchy
        stack = []
        curr_frame = frame
        while curr_frame:
            if curr_frame.f_code.co_filename == '<string>':
                frame_name = curr_frame.f_code.co_name
                # Capture variables for this specific frame
                frame_locals = {}
                for k, v in curr_frame.f_locals.items():
                    if k.startswith('__'):
                        continue
                    try:
                        frame_locals[k] = serialize_val(v)
                    except Exception:
                        frame_locals[k] = "<unserializable>"
                
                stack.append({
                    "name": frame_name,
                    "line": curr_frame.f_lineno,
                    "locals": frame_locals
                })
            curr_frame = curr_frame.f_back
        stack.reverse()

        # Locals of the active topmost frame
        active_locals = stack[-1]["locals"] if stack else {}

        self.steps.append({
            "line": lineno,
            "event": event,
            "locals": active_locals,
            "stack": stack,
            "stdout": self.stdout_buffer.getvalue()
        })

def run_trace(code_str, stdin_str=""):
    tracer = StepTracer()
    
    # Redirect stdout
    old_stdout = sys.stdout
    sys.stdout = tracer.stdout_buffer
    
    # Setup mocked inputs
    inputs = []
    if stdin_str:
        # Split by newlines or spaces (if space-separated tokens are provided)
        # If there's a newline, split by newline. Otherwise split by whitespace.
        if '\n' in stdin_str:
            inputs = [line.rstrip('\r\n') for line in stdin_str.split('\n')]
        else:
            inputs = stdin_str.split()
            
    input_idx = 0
    
    def mock_input(prompt=""):
        nonlocal input_idx
        if prompt:
            sys.stdout.write(str(prompt))
        if input_idx < len(inputs):
            val = inputs[input_idx]
            input_idx += 1
            return val
        return "" # Safe fallback instead of raising EOFError

    import builtins
    custom_builtins = builtins.__dict__.copy()
    custom_builtins["input"] = mock_input
    
    globals_dict = {"__builtins__": custom_builtins}
    locals_dict = {}
    
    error_msg = None
    try:
        compiled = compile(code_str, '<string>', 'exec')
        sys.settrace(tracer.trace_calls)
        exec(compiled, globals_dict, locals_dict)
    except Exception as e:
        # Get line number of exception inside `<string>`
        tb = sys.exc_info()[2]
        exc_line = 1
        for frame, lineno in traceback.walk_tb(tb):
            if frame.f_code.co_filename == '<string>':
                exc_line = lineno
        
        # Append exception details to trace
        tracer.steps.append({
            "line": exc_line,
            "event": "exception",
            "locals": {},
            "stdout": tracer.stdout_buffer.getvalue(),
            "exception": f"{type(e).__name__}: {str(e)}"
        })
        error_msg = f"{type(e).__name__}: {str(e)}"
    finally:
        sys.settrace(None)
        sys.stdout = old_stdout
 
    return {
        "steps": tracer.steps,
        "error": error_msg
    }
 
if __name__ == '__main__':
    try:
        # Read JSON payload from stdin
        input_data = sys.stdin.read()
        try:
            payload = json.loads(input_data)
            user_code = payload.get("code", "")
            stdin_str = payload.get("stdin", "")
        except json.JSONDecodeError:
            # Backward-compatible fallback for raw strings
            user_code = input_data
            stdin_str = ""
            
        result = run_trace(user_code, stdin_str)
        print(json.dumps(result))
    except Exception as e:
        print(json.dumps({
            "steps": [],
            "error": f"TracerError: {str(e)}"
        }))
