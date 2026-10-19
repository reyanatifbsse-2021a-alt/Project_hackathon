/**
 * AegisRuntime - Advanced Interactive DAG Pipeline Visualizer
 * Renders multi-step dependency graphs, live progressive execution states,
 * cryptographic PoA token gates, branch isolation barriers, and inline human clearance controls.
 */

class DagVisualizer {
  constructor(containerId, onNodeSelected) {
    this.container = document.getElementById(containerId);
    this.onNodeSelected = onNodeSelected;
    this.currentPlan = null;
    this.selectedStepId = null;
  }

  showLoadingState(message = 'Synthesizing Cognitive DAG...') {
    if (!this.container) return;
    this.container.innerHTML = `
      <div class="dag-standby-state">
        <div class="dag-radar-spinner"></div>
        <div class="dag-standby-title">${escapeHtml(message)}</div>
        <div class="dag-standby-sub">Parsing prompt entities, tools, dependencies, and security boundaries</div>
      </div>
    `;
  }

  render(plan, isInitial = false) {
    this.currentPlan = plan;
    if (!this.container) return;
    this.container.innerHTML = '';

    if (!plan || !plan.steps || plan.steps.length === 0) {
      this.container.innerHTML = `
        <div class="dag-standby-state">
          <svg class="dag-standby-icon" viewBox="0 0 24 24">
            <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/>
          </svg>
          <div class="dag-standby-title">Workflow DAG Standby</div>
          <div class="dag-standby-sub">Select a scenario preset above or type a natural language prompt to begin real-time agent execution.</div>
        </div>
      `;
      return;
    }

    // 1. Top Workflow Continuity Summary Card
    const summaryCard = document.createElement('div');
    summaryCard.className = 'dag-summary-card';
    summaryCard.id = 'dagSummaryBanner';

    const status = plan.status || 'PROPOSED';
    const isCompleted = status === 'COMPLETED_SUCCESSFULLY';
    const isPartial = status === 'PARTIALLY_COMPLETED_CONTINUED';
    const isHeld = status === 'INTERCEPTED_HELD';

    let statusClass = 'status-proposed';
    let statusLabel = 'INITIALIZED (READY)';
    if (isCompleted) {
      statusClass = 'status-completed';
      statusLabel = 'SUCCESSFULLY COMPLETED';
    } else if (isPartial) {
      statusClass = 'status-partial';
      statusLabel = 'WORKFLOW CONTINUITY ACTIVE';
    } else if (isHeld) {
      statusClass = 'status-held';
      statusLabel = 'INTERCEPTED / HELD';
    }

    summaryCard.innerHTML = `
      <div class="dag-summary-header">
        <div class="dag-summary-title-wrap">
          <span class="dag-summary-badge ${statusClass}">${escapeHtml(statusLabel)}</span>
          <span class="dag-task-id">TASK: ${escapeHtml(plan.task_id || 'ID-TBD')}</span>
        </div>
        <div class="dag-summary-metrics">
          <span class="metric-pill metric-exec">✔ <strong>${plan.completed_steps_count || 0}</strong> Executed</span>
          <span class="metric-pill metric-block">🛡 <strong>${plan.blocked_steps_count || 0}</strong> Intercepted</span>
          <span class="metric-pill metric-pause">⏸ <strong>${plan.paused_steps_count || 0}</strong> Isolated</span>
        </div>
      </div>
      <div class="dag-summary-text" id="dagSummaryText">
        ${escapeHtml(plan.summary || 'Cognitive task decomposed into dependency steps. Beginning point-of-action verification...')}
      </div>
    `;
    this.container.appendChild(summaryCard);

    // 2. DAG Flow Canvas
    const flowContainer = document.createElement('div');
    flowContainer.className = 'dag-pipeline-flow';
    flowContainer.id = 'dagPipelineFlow';

    // Group steps into sequence or parallel tracks
    plan.steps.forEach((step, index) => {
      // If not the first step, render dependency flow connector
      if (index > 0) {
        const connector = this.createFlowConnector(step, plan.steps[index - 1]);
        flowContainer.appendChild(connector);
      }

      // Render step node card
      const nodeEl = this.createStepNodeElement(step, index);
      flowContainer.appendChild(nodeEl);
    });

    this.container.appendChild(flowContainer);

    // Auto-select priority step
    const targetStep = plan.steps.find(s => s.status === 'BLOCKED' || s.status === 'HELD_FOR_REVIEW') || plan.steps[0];
    if (targetStep) {
      this.selectNode(targetStep.step_id);
    }
  }

  createFlowConnector(currStep, prevStep) {
    const conn = document.createElement('div');
    conn.className = 'dag-connector';
    conn.id = `conn-${currStep.step_id}`;

    const isDep = currStep.dependencies && currStep.dependencies.length > 0;
    const isUpstreamBlocked = prevStep && (prevStep.status === 'BLOCKED' || prevStep.status === 'PAUSED_DEPENDENCY');

    if (!isDep) {
      // Independent parallel branch
      conn.innerHTML = `
        <div class="dag-branch-pill independent">
          <span class="pulse-beacon green"></span>
          <span>⚡ Autonomous Parallel Safe Branch (Independent Execution)</span>
        </div>
      `;
    } else if (currStep.status === 'PAUSED_DEPENDENCY' || isUpstreamBlocked) {
      // Branch quarantined
      conn.innerHTML = `
        <div class="dag-branch-pill quarantined">
          <span class="pulse-beacon orange"></span>
          <span>🚫 Branch Quarantined (Dependency Upstream Intercepted)</span>
        </div>
      `;
    } else {
      // Standard sequential dependency
      conn.innerHTML = `
        <div class="dag-branch-arrow">
          <svg viewBox="0 0 24 24"><path d="M12 4v16m0 0l-5-5m5 5l5-5"/></svg>
          <span class="dag-arrow-text">Prerequisite Met ↳ Advancing to ${currStep.step_id}</span>
        </div>
      `;
    }
    return conn;
  }

  createStepNodeElement(step, index) {
    const el = document.createElement('div');
    el.className = `dag-step-node node-${step.status.toLowerCase()}`;
    el.onclick = () => {
      this.selectNode(step.step_id);
      if (window.openInspectorDrawer) window.openInspectorDrawer(step);
    };

    const stepNum = String(index + 1).padStart(2, '0');
    const isProtected = step.proposed_action ? step.proposed_action.is_protected : false;
    const toolName = step.proposed_action ? step.proposed_action.tool_name : 'unassigned';

    let badgeClass = 'badge-proposed';
    let badgeText = 'PROPOSED';
    let badgeIcon = '●';

    if (step.status === 'EXECUTED') {
      badgeClass = 'badge-executed';
      badgeText = 'EXECUTED (ALLOW)';
      badgeIcon = '✔';
    } else if (step.status === 'BLOCKED') {
      badgeClass = 'badge-blocked';
      badgeText = 'BLOCKED (INTERCEPTED)';
      badgeIcon = '🛡 ✖';
    } else if (step.status === 'HELD_FOR_REVIEW') {
      badgeClass = 'badge-held';
      badgeText = 'HELD FOR CLEARANCE';
      badgeIcon = '⚠ 👤';
    } else if (step.status === 'PAUSED_DEPENDENCY') {
      badgeClass = 'badge-paused';
      badgeText = 'BRANCH ISOLATED';
      badgeIcon = '⏸';
    }

    const hasDeps = step.dependencies && step.dependencies.length > 0;
    const depsMarkup = hasDeps
      ? `<span class="step-dep-pill">↳ Depends on: [${step.dependencies.join(', ')}]</span>`
      : `<span class="step-dep-pill independent">⚡ Independent Safe Branch</span>`;

    // Inline clearance action if held
    let inlineClearanceMarkup = '';
    if (step.status === 'HELD_FOR_REVIEW' && this.currentPlan) {
      inlineClearanceMarkup = `
        <div class="step-inline-clearance" onclick="event.stopPropagation()">
          <div class="clearance-head">
            <span class="pulse-beacon orange"></span>
            <strong>Dual-Control Clearance Required</strong>
          </div>
          <div class="clearance-desc">Sensitive operation suspended at point-of-action. Approve to mint PoA token and resume.</div>
          <div class="clearance-btn-group">
            <button class="btn-clearance-approve" onclick="window.handleInlineApproval('${this.currentPlan.task_id}', '${step.step_id}', true)">
              ✔ Approve & Resume DAG
            </button>
            <button class="btn-clearance-reject" onclick="window.handleInlineApproval('${this.currentPlan.task_id}', '${step.step_id}', false)">
              ✖ Reject / Halt
            </button>
          </div>
        </div>
      `;
    }

    el.innerHTML = `
      <div class="step-node-header">
        <div class="step-node-left">
          <span class="step-seq-pill">${stepNum}</span>
          <span class="step-id-text">${escapeHtml(step.step_id)}</span>
          ${depsMarkup}
        </div>
        <div class="step-node-right">
          <span class="status-badge ${badgeClass}" id="badge-${step.step_id}">${badgeIcon} ${badgeText}</span>
        </div>
      </div>

      <div class="step-node-body">
        <div class="step-node-title">${escapeHtml(step.title)}</div>
        <div class="step-node-desc">${escapeHtml(step.description)}</div>

        <div class="step-node-meta-grid">
          <div class="meta-item">
            <span class="meta-label">Tool:</span>
            <span class="meta-val tool-code">${escapeHtml(toolName)}</span>
          </div>
          <div class="meta-item">
            <span class="meta-label">Point-of-Action:</span>
            <span class="meta-val">${isProtected ? '<strong style="color: var(--accent-amber);">🔒 Gated (PoA Required)</strong>' : '<span style="color: var(--accent-emerald);">🔓 Safe Read</span>'}</span>
          </div>
          ${step.verification_result ? `
            <div class="meta-item">
              <span class="meta-label">Policy:</span>
              <span class="meta-val policy-code">${escapeHtml(step.verification_result.policy_id)}</span>
            </div>
          ` : ''}
        </div>

        ${step.notes ? `
          <div class="step-node-notes ${step.status === 'BLOCKED' ? 'note-blocked' : (step.status === 'PAUSED_DEPENDENCY' ? 'note-isolated' : '')}">
            ${escapeHtml(step.notes)}
          </div>
        ` : ''}

        ${inlineClearanceMarkup}

        <div class="step-card-footer">
          <button class="btn-inspect-step" onclick="event.stopPropagation(); if (window.openInspectorDrawer) window.openInspectorDrawer(dagVisualizer.currentPlan.steps.find(s => s.step_id === '${step.step_id}'));">
            🔍 View Safety Proof & Plain Breakdown →
          </button>
        </div>
      </div>
    `;

    return el;
  }

  markStepActive(stepId, stateType = 'evaluating') {
    const nodeEl = document.getElementById(`node-${stepId}`);
    if (!nodeEl) return;

    nodeEl.classList.remove('node-evaluating', 'node-verifying');
    if (stateType === 'evaluating') {
      nodeEl.classList.add('node-evaluating');
      const badge = document.getElementById(`badge-${stepId}`);
      if (badge) {
        badge.className = 'status-badge badge-running';
        badge.innerHTML = `<span class="pulse-beacon cyan"></span> EVALUATING`;
      }
    } else if (stateType === 'verifying') {
      nodeEl.classList.add('node-verifying');
      const badge = document.getElementById(`badge-${stepId}`);
      if (badge) {
        badge.className = 'status-badge badge-verifying';
        badge.innerHTML = `<span class="pulse-beacon amber"></span> POINT-OF-ACTION CHECK`;
      }
    }
  }

  updateStep(updatedStep) {
    if (!this.currentPlan) return;
    const idx = this.currentPlan.steps.findIndex(s => s.step_id === updatedStep.step_id);
    if (idx !== -1) {
      this.currentPlan.steps[idx] = updatedStep;
    }

    const oldEl = document.getElementById(`node-${updatedStep.step_id}`);
    if (oldEl) {
      const isSelected = oldEl.classList.contains('selected');
      const newEl = this.createStepNodeElement(updatedStep, idx);
      if (isSelected) newEl.classList.add('selected');
      oldEl.replaceWith(newEl);
    }

    // Update connector if present
    const connEl = document.getElementById(`conn-${updatedStep.step_id}`);
    if (connEl && idx > 0) {
      const prevStep = this.currentPlan.steps[idx - 1];
      const newConn = this.createFlowConnector(updatedStep, prevStep);
      connEl.replaceWith(newConn);
    }

    if (this.selectedStepId === updatedStep.step_id && this.onNodeSelected) {
      this.onNodeSelected(updatedStep);
    }
  }

  isolateStep(stepId, reason) {
    if (!this.currentPlan) return;
    const step = this.currentPlan.steps.find(s => s.step_id === stepId);
    if (step) {
      step.status = 'PAUSED_DEPENDENCY';
      step.notes = reason || 'Branch Quarantined: Dependent upstream failed.';
      this.updateStep(step);
    }
  }

  selectNode(stepId) {
    this.selectedStepId = stepId;
    if (!this.currentPlan) return;

    const allNodes = this.container.querySelectorAll('.dag-step-node');
    allNodes.forEach(n => n.classList.remove('selected'));

    const activeNode = document.getElementById(`node-${stepId}`);
    if (activeNode) {
      activeNode.classList.add('selected');
      activeNode.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }

    const step = this.currentPlan.steps.find(s => s.step_id === stepId);
    if (step && this.onNodeSelected) {
      this.onNodeSelected(step);
    }
  }
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

window.DagVisualizer = DagVisualizer;
