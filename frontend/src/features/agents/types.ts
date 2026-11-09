// Mirrors backend/app/schemas/agent_config.py and api/v1/agents.py.

export type Provider = 'rule_based' | 'gemini' | 'openai'

export interface AgentConfig {
  name: string
  version: number
  description: string
  provider: Provider
  model_id: string
  temperature: number
  prompt_version: string
  system_prompt: string | null
  tools: string[]
  max_steps: number
  max_tool_calls: number
  timeout_s: number
  max_retries: number
}

export interface AgentSummary {
  id: string
  name: string
  version: number
  description: string
  provider: Provider
  model_id: string
  status: 'active' | 'archived'
  is_locked: boolean
  tool_count: number
  updated_at: string
}

export interface AgentDetail extends AgentSummary {
  created_at: string
  config: AgentConfig
  versions: { id: string; version: number; status: string; is_locked: boolean; created_at: string }[]
  can_edit: boolean
}

export interface AgentWriteResult {
  outcome: 'created' | 'updated' | 'new_version' | 'unchanged'
  agent: AgentDetail
}

export interface ProviderStatus {
  provider: Provider
  label: string
  configured: boolean
  available: boolean
  note: string
}

export const RULE_BASED_PROFILES = [
  { value: 'v1', label: 'v1: follows the SOPs' },
  { value: 'v2_flawed', label: 'v2_flawed: deliberate flaws for regression demos' },
]
