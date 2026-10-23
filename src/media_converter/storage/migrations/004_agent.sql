CREATE TABLE agent_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE conversations (conversation_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
CREATE TABLE agent_references (reference_id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, payload TEXT NOT NULL, revoked INTEGER NOT NULL DEFAULT 0);
CREATE TABLE agent_turns (turn_id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, state TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE messages (conversation_id TEXT NOT NULL, sequence INTEGER NOT NULL, turn_id TEXT, payload TEXT NOT NULL, PRIMARY KEY(conversation_id,sequence));
CREATE TABLE tool_invocations (invocation_id TEXT PRIMARY KEY, turn_id TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE settings_proposals (proposal_id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE agent_summaries (conversation_id TEXT PRIMARY KEY, through_sequence INTEGER NOT NULL, payload TEXT NOT NULL);
