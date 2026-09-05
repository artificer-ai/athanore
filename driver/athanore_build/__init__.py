"""Driver workflows: athanore v0 dispatching the v1 serial task plan.

This package runs against the **MVP** API (`AthanoreWorkflow`,
`AthanoreACPAgent`, `human_input`, `current_task`) and never imports the
v1 package it is building. The two are both called `athanore`, so they
live in separate environments and only ever meet over the container
boundary (D67).

    docker compose --profile drive up -d orchestrator
    ./scripts/drive.sh submit --only T003
"""
