

def handle_import(agent, recp, agent_type, blackbox=None):
    f = agent.call_remote(recp, 'handle_import', agent_type, blackbox)
    return f
