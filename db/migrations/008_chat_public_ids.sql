-- Chat sessions are addressed by an unguessable id (sequential ids would let anyone enumerate other people's chats).
ALTER TABLE chat_sessions ADD COLUMN public_id UUID NOT NULL DEFAULT gen_random_uuid();
CREATE UNIQUE INDEX chat_sessions_public_id_idx ON chat_sessions (public_id);
