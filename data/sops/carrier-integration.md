---
slug: carrier-integration
title: Carrier Integration Incident Handling
document_type: procedure
version: 1
---

## s1. Purpose and scope

This procedure covers situations where a carrier's status system cannot be reached or returns unusable
data. In these cases the latest shipment status cannot be confirmed from the carrier.

## s2. Carrier API timeouts

If the carrier status request times out, retry once. If it times out again, do not infer the shipment's
status, location or ETA. Use the last tracking scan as the last known position and say clearly that the
latest status cannot be confirmed right now. If there has been no new scan for more than twenty-four
hours, escalate the case with severity medium and mention the carrier system issue in the reason.

## s3. Malformed carrier responses

If the carrier returns a response that cannot be read, treat it like a timeout: do not use any of its
content, rely on the last valid tracking scan, and escalate if the shipment has been silent for more
than twenty-four hours.

## s4. Carrier status unavailable

If the carrier reports that it has no status for the shipment, tell the customer that the carrier has
not provided an update yet. Escalate if this continues for more than twenty-four hours after the last
scan, or immediately if the shipment is past its promised delivery date.
