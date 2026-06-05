CREATE TABLE IF NOT EXISTS schema_migrations (
    version VARCHAR(255) PRIMARY KEY,
    applied_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE users ADD COLUMN IF NOT EXISTS payload JSONB DEFAULT '{}'::jsonb;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS payload JSONB DEFAULT '{}'::jsonb;
ALTER TABLE interviews ADD COLUMN IF NOT EXISTS payload JSONB DEFAULT '{}'::jsonb;
ALTER TABLE resumes ADD COLUMN IF NOT EXISTS text TEXT;
ALTER TABLE resumes ADD COLUMN IF NOT EXISTS payload JSONB DEFAULT '{}'::jsonb;
ALTER TABLE execution_logs ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}'::jsonb;
ALTER TABLE execution_logs ADD COLUMN IF NOT EXISTS payload JSONB DEFAULT '{}'::jsonb;
ALTER TABLE dsa_problems ADD COLUMN IF NOT EXISTS category VARCHAR(255);
ALTER TABLE dsa_problems ADD COLUMN IF NOT EXISTS payload JSONB DEFAULT '{}'::jsonb;
ALTER TABLE dsa_submissions ADD COLUMN IF NOT EXISTS tool_result JSONB DEFAULT '{}'::jsonb;
ALTER TABLE dsa_submissions ADD COLUMN IF NOT EXISTS reasoning_evaluation JSONB DEFAULT '{}'::jsonb;
ALTER TABLE dsa_submissions ADD COLUMN IF NOT EXISTS payload JSONB DEFAULT '{}'::jsonb;
ALTER TABLE aptitude_questions ADD COLUMN IF NOT EXISTS payload JSONB DEFAULT '{}'::jsonb;
ALTER TABLE technical_questions ADD COLUMN IF NOT EXISTS difficulty VARCHAR(50);
ALTER TABLE technical_questions ADD COLUMN IF NOT EXISTS answer_mode VARCHAR(50);
ALTER TABLE technical_questions ADD COLUMN IF NOT EXISTS timer_seconds INTEGER;
ALTER TABLE technical_questions ADD COLUMN IF NOT EXISTS payload JSONB DEFAULT '{}'::jsonb;
ALTER TABLE technical_answers ADD COLUMN IF NOT EXISTS matched_keywords TEXT[];
ALTER TABLE technical_answers ADD COLUMN IF NOT EXISTS safety_flags TEXT[];
ALTER TABLE technical_answers ADD COLUMN IF NOT EXISTS answer_mode VARCHAR(50);
ALTER TABLE technical_answers ADD COLUMN IF NOT EXISTS time_taken_seconds INTEGER;
ALTER TABLE technical_answers ADD COLUMN IF NOT EXISTS timer_expired BOOLEAN DEFAULT false;
ALTER TABLE technical_answers ADD COLUMN IF NOT EXISTS speech_metrics JSONB DEFAULT '{}'::jsonb;
ALTER TABLE technical_answers ADD COLUMN IF NOT EXISTS proctor_events JSONB DEFAULT '[]'::jsonb;
ALTER TABLE technical_answers ADD COLUMN IF NOT EXISTS repeat_count INTEGER DEFAULT 0;
ALTER TABLE technical_answers ADD COLUMN IF NOT EXISTS paraphrase_count INTEGER DEFAULT 0;
ALTER TABLE technical_answers ADD COLUMN IF NOT EXISTS answer_source VARCHAR(100);
ALTER TABLE technical_answers ADD COLUMN IF NOT EXISTS rubric JSONB DEFAULT '{}'::jsonb;
ALTER TABLE technical_answers ADD COLUMN IF NOT EXISTS evidence JSONB DEFAULT '[]'::jsonb;
ALTER TABLE technical_answers ADD COLUMN IF NOT EXISTS improvement_suggestions JSONB DEFAULT '[]'::jsonb;
ALTER TABLE technical_answers ADD COLUMN IF NOT EXISTS confidence_score NUMERIC(5,2);
ALTER TABLE technical_answers ADD COLUMN IF NOT EXISTS communication_score NUMERIC(5,2);
ALTER TABLE technical_answers ADD COLUMN IF NOT EXISTS bias_guardrails JSONB DEFAULT '[]'::jsonb;
ALTER TABLE technical_answers ADD COLUMN IF NOT EXISTS evaluation_agent VARCHAR(255);
ALTER TABLE technical_answers ADD COLUMN IF NOT EXISTS evaluation_provider VARCHAR(100);
ALTER TABLE technical_answers ADD COLUMN IF NOT EXISTS evaluation_model VARCHAR(255);
ALTER TABLE technical_answers ADD COLUMN IF NOT EXISTS evaluated_at TIMESTAMPTZ;
ALTER TABLE technical_answers ADD COLUMN IF NOT EXISTS internal_evaluation_trace JSONB DEFAULT '{}'::jsonb;
ALTER TABLE technical_answers ADD COLUMN IF NOT EXISTS payload JSONB DEFAULT '{}'::jsonb;
ALTER TABLE hr_questions ADD COLUMN IF NOT EXISTS difficulty VARCHAR(50);
ALTER TABLE hr_questions ADD COLUMN IF NOT EXISTS answer_mode VARCHAR(50);
ALTER TABLE hr_questions ADD COLUMN IF NOT EXISTS timer_seconds INTEGER;
ALTER TABLE hr_questions ADD COLUMN IF NOT EXISTS payload JSONB DEFAULT '{}'::jsonb;
ALTER TABLE hr_answers ADD COLUMN IF NOT EXISTS matched_keywords TEXT[];
ALTER TABLE hr_answers ADD COLUMN IF NOT EXISTS safety_flags TEXT[];
ALTER TABLE hr_answers ADD COLUMN IF NOT EXISTS answer_mode VARCHAR(50);
ALTER TABLE hr_answers ADD COLUMN IF NOT EXISTS time_taken_seconds INTEGER;
ALTER TABLE hr_answers ADD COLUMN IF NOT EXISTS timer_expired BOOLEAN DEFAULT false;
ALTER TABLE hr_answers ADD COLUMN IF NOT EXISTS speech_metrics JSONB DEFAULT '{}'::jsonb;
ALTER TABLE hr_answers ADD COLUMN IF NOT EXISTS proctor_events JSONB DEFAULT '[]'::jsonb;
ALTER TABLE hr_answers ADD COLUMN IF NOT EXISTS repeat_count INTEGER DEFAULT 0;
ALTER TABLE hr_answers ADD COLUMN IF NOT EXISTS paraphrase_count INTEGER DEFAULT 0;
ALTER TABLE hr_answers ADD COLUMN IF NOT EXISTS answer_source VARCHAR(100);
ALTER TABLE hr_answers ADD COLUMN IF NOT EXISTS rubric JSONB DEFAULT '{}'::jsonb;
ALTER TABLE hr_answers ADD COLUMN IF NOT EXISTS evidence JSONB DEFAULT '[]'::jsonb;
ALTER TABLE hr_answers ADD COLUMN IF NOT EXISTS improvement_suggestions JSONB DEFAULT '[]'::jsonb;
ALTER TABLE hr_answers ADD COLUMN IF NOT EXISTS confidence_score NUMERIC(5,2);
ALTER TABLE hr_answers ADD COLUMN IF NOT EXISTS communication_score NUMERIC(5,2);
ALTER TABLE hr_answers ADD COLUMN IF NOT EXISTS bias_guardrails JSONB DEFAULT '[]'::jsonb;
ALTER TABLE hr_answers ADD COLUMN IF NOT EXISTS evaluation_agent VARCHAR(255);
ALTER TABLE hr_answers ADD COLUMN IF NOT EXISTS evaluation_provider VARCHAR(100);
ALTER TABLE hr_answers ADD COLUMN IF NOT EXISTS evaluation_model VARCHAR(255);
ALTER TABLE hr_answers ADD COLUMN IF NOT EXISTS evaluated_at TIMESTAMPTZ;
ALTER TABLE hr_answers ADD COLUMN IF NOT EXISTS internal_evaluation_trace JSONB DEFAULT '{}'::jsonb;
ALTER TABLE hr_answers ADD COLUMN IF NOT EXISTS payload JSONB DEFAULT '{}'::jsonb;
ALTER TABLE reports ADD COLUMN IF NOT EXISTS executive_summary TEXT;
ALTER TABLE reports ADD COLUMN IF NOT EXISTS what_went_wrong JSONB DEFAULT '[]'::jsonb;
ALTER TABLE reports ADD COLUMN IF NOT EXISTS next_time_suggestions JSONB DEFAULT '[]'::jsonb;
ALTER TABLE reports ADD COLUMN IF NOT EXISTS action_plan JSONB DEFAULT '[]'::jsonb;
ALTER TABLE reports ADD COLUMN IF NOT EXISTS section_analyses JSONB DEFAULT '[]'::jsonb;
ALTER TABLE reports ADD COLUMN IF NOT EXISTS generation_provider VARCHAR(100);
ALTER TABLE reports ADD COLUMN IF NOT EXISTS communication_summary JSONB DEFAULT '{}'::jsonb;
ALTER TABLE reports ADD COLUMN IF NOT EXISTS proctor_summary JSONB DEFAULT '{}'::jsonb;
ALTER TABLE reports ADD COLUMN IF NOT EXISTS payload JSONB DEFAULT '{}'::jsonb;
ALTER TABLE roadmaps ADD COLUMN IF NOT EXISTS payload JSONB DEFAULT '{}'::jsonb;
ALTER TABLE bot_conversations ADD COLUMN IF NOT EXISTS payload JSONB DEFAULT '{}'::jsonb;
ALTER TABLE practice_sessions ADD COLUMN IF NOT EXISTS payload JSONB DEFAULT '{}'::jsonb;

CREATE TABLE IF NOT EXISTS aptitude_results (
    interview_id UUID PRIMARY KEY REFERENCES interviews(id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    score NUMERIC(5,2),
    correct_count INTEGER,
    wrong_count INTEGER,
    result JSONB DEFAULT '{}'::jsonb,
    submitted_at TIMESTAMPTZ DEFAULT NOW(),
    payload JSONB DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS round_runtimes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    interview_id UUID NOT NULL REFERENCES interviews(id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    round_name VARCHAR(50) NOT NULL,
    status VARCHAR(50) NOT NULL,
    current_question_id UUID,
    state JSONB DEFAULT '{}'::jsonb,
    payload JSONB DEFAULT '{}'::jsonb,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (interview_id, round_name)
);

CREATE TABLE IF NOT EXISTS workflow_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    interview_id UUID NOT NULL REFERENCES interviews(id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    kind VARCHAR(100) NOT NULL,
    status VARCHAR(50) NOT NULL,
    current_node VARCHAR(255),
    queue_backend VARCHAR(100),
    external_job_id TEXT,
    attempt INTEGER DEFAULT 0,
    max_attempts INTEGER DEFAULT 1,
    cancel_requested BOOLEAN DEFAULT false,
    queued_at TIMESTAMPTZ,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    last_heartbeat_at TIMESTAMPTZ,
    result JSONB DEFAULT '{}'::jsonb,
    error TEXT,
    payload JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS agent_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    interview_id UUID REFERENCES interviews(id) ON DELETE CASCADE,
    workflow_job_id UUID REFERENCES workflow_jobs(id) ON DELETE SET NULL,
    event_type VARCHAR(50) NOT NULL,
    agent VARCHAR(255) NOT NULL,
    message TEXT NOT NULL,
    step VARCHAR(50),
    metadata JSONB DEFAULT '{}'::jsonb,
    payload JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS agent_memories (
    id TEXT PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    memory_type VARCHAR(100) NOT NULL,
    source_id TEXT NOT NULL,
    source_route VARCHAR(255),
    source_agent VARCHAR(255),
    text TEXT NOT NULL,
    metadata JSONB DEFAULT '{}'::jsonb,
    importance NUMERIC(5,2) DEFAULT 0.5,
    privacy_scope VARCHAR(100) DEFAULT 'user',
    embedding JSONB DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS graph_checkpoints (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_job_id UUID REFERENCES workflow_jobs(id) ON DELETE CASCADE,
    interview_id UUID REFERENCES interviews(id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    graph_name VARCHAR(255) NOT NULL,
    checkpoint_key VARCHAR(255) NOT NULL,
    state JSONB DEFAULT '{}'::jsonb,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (graph_name, checkpoint_key)
);

CREATE INDEX IF NOT EXISTS idx_workflow_jobs_interview_id ON workflow_jobs(interview_id);
CREATE INDEX IF NOT EXISTS idx_workflow_jobs_status ON workflow_jobs(status);
CREATE INDEX IF NOT EXISTS idx_agent_events_interview_id ON agent_events(interview_id);
CREATE INDEX IF NOT EXISTS idx_agent_events_workflow_job_id ON agent_events(workflow_job_id);
CREATE INDEX IF NOT EXISTS idx_agent_memories_user_type ON agent_memories(user_id, memory_type);
CREATE INDEX IF NOT EXISTS idx_agent_memories_source ON agent_memories(source_id);
CREATE INDEX IF NOT EXISTS idx_graph_checkpoints_job ON graph_checkpoints(workflow_job_id);
CREATE INDEX IF NOT EXISTS idx_round_runtimes_interview_round ON round_runtimes(interview_id, round_name);
