import pytest
import subprocess
import time
import requests
import os
import sys
import json # For node_api_post if it uses json kwarg

# Constants for node subprocesses
PYTHON_EXECUTABLE = sys.executable
# Correct NODE_SCRIPT_PATH by determining it relative to this conftest.py file
# This conftest.py is in tests/integration/
# NODE_SCRIPT_PATH should be ../../cmd/node/main.py from this file's location.
CONTEST_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT_FOR_CONTEST = os.path.dirname(os.path.dirname(CONTEST_DIR)) # (tests/integration -> tests -> project_root)
NODE_SCRIPT_PATH = os.path.abspath(os.path.join(PROJECT_ROOT_FOR_CONTEST, 'cmd/node/main.py'))
DEFAULT_HOST = "127.0.0.1"

# Helper function to start a node subprocess
def _start_node_subprocess(port: int, host: str = DEFAULT_HOST, seed_nodes: list = None, cwd=None, log_dir="logs/test_nodes"):
    if seed_nodes is None: seed_nodes = []
    os.makedirs(log_dir, exist_ok=True)
    log_file_stdout = os.path.join(log_dir, f"node_{port}_stdout.log")
    log_file_stderr = os.path.join(log_dir, f"node_{port}_stderr.log")

    cmd = [PYTHON_EXECUTABLE, NODE_SCRIPT_PATH, host, str(port)] + seed_nodes

    stdout_file = open(log_file_stdout, 'w')
    stderr_file = open(log_file_stderr, 'w')

    process = subprocess.Popen(cmd, stdout=stdout_file, stderr=stderr_file, text=True, cwd=cwd, bufsize=1, universal_newlines=True)

    process.node_log_files = {"stdout": log_file_stdout, "stderr": log_file_stderr, "stdout_handle": stdout_file, "stderr_handle": stderr_file}

    ready = False; retries = 20 # approx 10 seconds
    for _ in range(retries):
        time.sleep(0.5)
        try:
            if requests.get(f"http://{host}:{port}/ping", timeout=1).status_code == 200:
                ready = True; break
        except requests.exceptions.RequestException: pass

    if not ready:
        print(f"Node {port} did not become ready. Terminating. Check logs: {log_file_stdout}, {log_file_stderr}")
        stdout_file.close()
        stderr_file.close()
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        return None
    return process

# Helper function to terminate a node subprocess
def _terminate_node_subprocess(process: subprocess.Popen, port: int):
    if hasattr(process, 'node_log_files'):
        if process.node_log_files['stdout_handle'] and not process.node_log_files['stdout_handle'].closed:
            process.node_log_files['stdout_handle'].close()
        if process.node_log_files['stderr_handle'] and not process.node_log_files['stderr_handle'].closed:
            process.node_log_files['stderr_handle'].close()

    if process and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

# API Helper Functions (pytest won't automatically make these fixtures unless decorated)
# These can be imported directly by test files in this directory.
def node_api_get(port: int, endpoint: str, host: str = DEFAULT_HOST, timeout=5): # Increased default timeout
    try:
        url = f"http://{host}:{port}{endpoint}"
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException:
        return None

def node_api_post(port: int, endpoint: str, data: dict, host: str = DEFAULT_HOST, timeout=5): # Increased default timeout
    try:
        url = f"http://{host}:{port}{endpoint}"
        # Using json parameter for requests.post correctly serializes dict to JSON body
        response = requests.post(url, json=data, timeout=timeout)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException:
        return None

# Fixture for the project root directory (session-scoped)
@pytest.fixture(scope="session")
def project_root_dir_session():
    # This conftest.py is in tests/integration/. So ../.. is the project root.
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))

# Fixture to manage running node subprocesses for tests
@pytest.fixture
def running_nodes_manager(project_root_dir_session, request):
    processes_ports = {}
    # Create a unique log directory for each test function that uses this fixture
    log_dir = os.path.join(project_root_dir_session, "logs", "test_nodes", request.node.name.replace("[", "_").replace("]", "")) # Sanitize node name for dir

    def _starter_function(nodes_config: list):
        nonlocal processes_ports, log_dir
        started_node_infos = []
        for config in nodes_config:
            port = config["port"]
            seeds = config.get("seeds", [])
            host = config.get("host", DEFAULT_HOST)

            proc = _start_node_subprocess(port, host, seed_nodes=seeds, cwd=project_root_dir_session, log_dir=log_dir)
            if proc:
                processes_ports[port] = proc
                started_node_infos.append({
                    "host": host, "port": port, "address": f"http://{host}:{port}",
                    "log_files": proc.node_log_files
                })
            else:
                for p, pr_to_kill in processes_ports.items(): # Terminate already started nodes by this manager instance
                    _terminate_node_subprocess(pr_to_kill, p)
                pytest.fail(f"Failed to start node on port {port}. Check logs in {log_dir}")

        if not processes_ports and nodes_config: # Fail if configs were provided but no nodes started
             pytest.fail("No nodes were started by the manager despite configuration being provided.")
        return started_node_infos

    yield _starter_function # The test runs here

    # Teardown: Ensure all managed nodes are terminated and logs are optionally printed
    print("\n--- Integration Test Node Logs Teardown ---")
    for port, process in processes_ports.items():
        print(f"\n--- Logs for Node on port {port} (Test: {request.node.name}) ---")

        _terminate_node_subprocess(process, port) # Ensures file handles are closed by _terminate

        log_files = getattr(process, 'node_log_files', None)
        if log_files:
            for log_type, log_path in log_files.items():
                if log_type.endswith("_handle"): continue
                print(f"--- {log_type.upper()} for Node {port} from {log_path} ---")
                try:
                    with open(log_path, 'r') as f:
                        log_content = f.read()
                        print(log_content if log_content.strip() else "<empty log file>")
                except FileNotFoundError:
                    print("<log file not found>")
                except Exception as e:
                    print(f"<error reading log file: {e}>")
        else:
            print(f"Node {port} log files info not found on process object.")

        if process.poll() is None: # Final check if process somehow still running
             _terminate_node_subprocess(process, port)

print("Integration conftest.py loaded: Node management fixtures are available for integration tests.")
