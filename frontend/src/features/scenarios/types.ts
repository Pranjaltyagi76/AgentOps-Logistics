// Mirrors backend/app/schemas/scenario.py and scenario_api.py.

export type ScenarioStatus = 'draft' | 'active' | 'archived'
export type Difficulty = 'easy' | 'medium' | 'hard'

export interface ScenarioSummary {
  id: string
  scenario_key: string
  version: number
  title: string
  category: string
  difficulty: Difficulty
  status: ScenarioStatus
  tags: string[]
  is_locked: boolean
  updated_at: string
}

export interface ScenarioPage {
  items: ScenarioSummary[]
  next_cursor: string | null
  total: number
}

export interface Shipment {
  shipment_id: string
  customer_id: string
  carrier_id: string | null
  origin_city: string
  destination_city: string
  service_level: 'standard' | 'express'
  status: string
  promised_delivery_date: string
  current_eta: string | null
  eta_status: string
  recipient_name: string | null
  delivery_attempts: number
  next_attempt_date: string | null
  created_at: string
}

export interface TrackingEvent {
  shipment_id: string
  seq: number
  timestamp: string
  location: string
  event_code: string
  description: string
}

export interface CarrierStatus {
  carrier_id: string
  name: string
  status: 'operational' | 'degraded' | 'outage'
  notice: string | null
  updated_at: string
}

export interface Ticket {
  ticket_id: string
  customer_id: string
  shipment_id: string | null
  related_shipment_ids: string[]
  status: string
  channel: string
  opened_at: string
  subject: string
  last_customer_message: string | null
}

export interface MockData {
  shipments: Shipment[]
  tracking_events: TrackingEvent[]
  carrier_status: CarrierStatus[]
  tickets: Ticket[]
}

export interface VisibleScenario {
  scenario_id: string
  version: number
  title: string
  description: string
  category: string
  difficulty: Difficulty
  as_of: string
  customer_message: string
  visible_context: Record<string, string>
  mock_data: MockData
  permitted_documents: string[]
  available_tools: string[]
  tags: string[]
}

export interface GroundTruth {
  root_cause: string
  required_evidence: string[]
  required_tools: string[]
  required_actions: string[]
  forbidden_actions: string[]
  expected_escalation: boolean
  supported_eta: string | null
  sequence_constraints: [string, string][]
  response_constraints: string[]
}

export interface FaultInjection {
  tool: string
  error: string
  latency_ms: number
  calls: number[] | 'all'
}

export interface HiddenScenario {
  ground_truth: GroundTruth
  evaluation: {
    weights: Record<string, number>
    pass_threshold: number
    rubric: string | null
  }
  fault_injection: FaultInjection[]
  author_note: string | null
}

export interface ScenarioVersion {
  id: string
  version: number
  status: ScenarioStatus
  is_locked: boolean
  created_at: string
}

export interface ScenarioDetail extends ScenarioSummary {
  created_at: string
  versions: ScenarioVersion[]
  visible: VisibleScenario
  hidden: HiddenScenario | null
  can_edit: boolean
}

export interface ValidationIssue {
  loc: string
  msg: string
}

export interface ValidationReport {
  valid: boolean
  errors: ValidationIssue[]
  warnings: ValidationIssue[]
}

export interface WriteResult {
  outcome: 'created' | 'updated' | 'new_version' | 'unchanged'
  scenario: ScenarioDetail
  warnings: ValidationIssue[]
}

export interface ImportResponse {
  results: {
    scenario_key: string | null
    version: number | null
    outcome: 'created' | 'updated' | 'unchanged' | 'error'
    id: string | null
    errors: ValidationIssue[] | null
  }[]
  created: number
  updated: number
  unchanged: number
  errors: number
}

export interface Taxonomy {
  version: string
  categories: string[]
  difficulties: Difficulty[]
  statuses: ScenarioStatus[]
  root_causes: { label: string; family: string; description: string }[]
  tools: { name: string; kind: 'read' | 'mock_write'; policy_gated: boolean }[]
  response_constraints: { name: string; gate: boolean }[]
  failure_types: string[]
  sop_documents: { slug: string; title: string; sections: { id: string; title: string }[] }[]
}

export interface ScenarioFilters {
  q?: string
  category?: string
  difficulty?: string
  status?: string
  tag?: string
}
