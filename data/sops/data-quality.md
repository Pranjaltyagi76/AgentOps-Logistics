---
slug: data-quality
title: Tracking Data Quality Procedure
document_type: procedure
version: 1
---

## s1. Purpose and scope

This procedure explains what to do when tracking data is wrong or contradictory. Customer replies must
be based on reliable data only, and bad data must be reported so it can be corrected.

## s2. Invalid or future-dated timestamps

A tracking event dated in the future, or one that contradicts the shipment status (for example a
"delivered" event while the shipment is still in transit), is invalid. Ignore it when describing the
shipment's position and use the latest valid event instead. Tell the customer the entry is a tracking
error. Open a support ticket with category data_correction that names the shipment and the invalid
event. Do not escalate for this reason alone.

## s3. Inconsistent shipment statuses

When the shipment record and the latest valid tracking event disagree, trust the most recent valid scan,
tell the customer the information is being checked, and open a data_correction support ticket.

## s4. Missing identifiers

If the customer does not give a shipment or tracking number and the account or ticket does not identify
a single shipment, ask the customer which order they mean before sharing shipment details. Do not guess
between several shipments.
