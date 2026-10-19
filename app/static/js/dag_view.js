/**
 * AegisRuntime - Interactive DAG & Step Node Renderer
 * Visualizes multi-step dependency graphs, runtime interventions, and branch isolation.
 */

class DagVisualizer {
  constructor(containerId, onNodeSelected) {
    this.container = document.getElementById(containerId);
    this.onNodeSelected = onNodeSelected;
    this.currentPlan = null;
    this.selectedStepId = null;
  }

  render(plan) {
    this.currentPlan = plan;
    if (!this.container) return;
    this.container.innerHTML = '';

    if (!plan || !plan.steps || plan.steps.length === 0) {
      this.container.innerHTML = `
        <div style="text-align: center; color: var(--text-dim); padding: 3rem 1rem;">
          <svg style="width: 48px; height: 48px; margin-bottom: 1rem; fill: currentColor;" viewBox="0 0 24 24">
            <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/>
          </svg>
          <div style="font-weight: 600; font-size: 1rem;">Awaiting Task Input</div>
          <div style="font-size: 0.8rem; margin-top: 0.25rem;">Select a demonstration scenario above or enter a custom prompt.</div>
        </div>
      `;
      return;
    }

    // Render Execution Summary Bar
    const summaryCard = document.createElement('div');
    summaryCard.className = 'glass-panel';
    summaryCard.style.padding = '0.75rem 1.25rem';
    summaryCard.style.marginBottom = '1rem';
    summaryCard.style.background = 'rgba(14, 21, 38, 0.9)';
    summaryCard.style.borderLeft = plan.status === 'COMPLETED_SUCCESSFULLY' ? '4px solid var(--accent-emerald)' : (plan.status === 'PARTIALLY_COMPLETED_CONTINUED' ? '4px solid var(--accent-cyan)' : '4px solid var(--accent-rose)');

    summaryCard.innerHTML = `
      <div style="display: flex; justify-content: space-between; align-items: center; font-size: 0.8rem;">
        <div>
          <span style="font-weight: 700; color: var(--text-main);">${escapeHtml(plan.status)}</span>
          <span style="color: var(--text-muted); margin-left: 0.75rem;">${escapeHtml(plan.summary || '')}</span>
        </div>
        <div style="display: flex; gap: 0.75rem; font-family: var(--font-mono); font-size: 0.75rem;">
          <span style="color: var(--accent-emerald);">✔ ${plan.completed_steps_count || 0} Executed</span>
          <span style="color: var(--accent-rose);">✖ ${plan.blocked_steps_count || 0} Blocked</span>
          <span style="color: var(--accent-amber);">⏸ ${plan.paused_steps_count || 0} Isolated</span>
        </div>
      </div>
    `;
    this.container.appendChild(summaryCard);

    // Render Steps in DAG layout
    const stepsList = document.createElement('div');
    stepsList.style.display = 'flex';
    stepsList.style.flexDirection = 'column';
    stepsList.style.gap = '1rem';

    plan.steps.forEach((step, index) => {
      const nodeEl = this.createStepNodeElement(step, index);
      stepsList.appendChild(nodeEl);
    });

    this.container.appendChild(stepsList);

    // Auto-select the first blocked or held node, or the first step
    if (!this.selectedStepId) {
      const priorityStep = plan.steps.find(s => s.status === 'BLOCKED' || s.status === 'HELD_FOR_REVIEW') || plan.steps[0];
      if (priorityStep) {
        this.selectNode(priorityStep.step_id);
      }
    } else {
      this.selectNode(this.selectedStepId);
    }
  }

  createStepNodeElement(step, index) {
    const el = document.createElement('div');
    el.className = `dag-step-node status-${step.status}`;
    el.id = `node-${step.step_id}`;
    el.onclick = () => this.selectNode(step.step_id);

    let badgeClass = 'badge-proposed';
    let badgeLabel = step.status;
    let badgeIcon = '●';

    if (step.status === 'EXECUTED') {
      badgeClass = 'badge-executed';
      badgeLabel = 'EXECUTED';
      badgeIcon = '✔';
    } else if (step.status === 'BLOCKED') {
      badgeClass = 'badge-blocked';
      badgeLabel = 'BLOCKED (INTERCEPTED)';
      badgeIcon = '🛡 ✖';
    } else if (step.status === 'HELD_FOR_REVIEW') {
      badgeClass = 'badge-held';
      badgeLabel = 'HELD FOR HUMAN REVIEW';
      badgeIcon = '⚠';
    } else if (step.status === 'PAUSED_DEPENDENCY') {
      badgeClass = 'badge-paused';
      badgeLabel = 'BRANCH ISOLATED';
      badgeIcon = '⏸';
    }

    const depsInfo = step.dependencies && step.dependencies.length > 0 
      ? `<span style="color: var(--text-dim); font-size: 0.7rem; font-family: var(--font-mono);">↳ Depends on: [${step.dependencies.join(', ')}]</span>` 
      : `<span style="color: var(--accent-cyan); font-size: 0.7rem; font-family: var(--font-mono);">⚡ Independent Branch</span>`;

    const toolName = step.proposed_action ? step.proposed_action.tool_name : 'unassigned';
    const isProtected = step.proposed_action ? step.proposed_action.is_protected : false;

    el.innerHTML = `
      <div class="step-node-header">
        <div style="display: flex; align-items: center; gap: 0.6rem;">
          <span class="step-node-id">${step.step_id}</span>
          ${depsInfo}
        </div>
        <span class="status-badge ${badgeClass}">${badgeIcon} ${badgeLabel}</span>
      </div>
      <div class="step-node-title">${escapeHtml(step.title)}</div>
      <div class="step-node-desc">${escapeHtml(step.description)}</div>
      <div class="step-node-tool-meta">
        <span>🔧 Tool: <strong style="color: var(--text-main);">${escapeHtml(toolName)}</strong></span>
        <span>${isProtected ? '<strong style="color: var(--accent-amber);">🔒 Protected Tool</strong>' : '<span style="color: var(--accent-emerald);">🔓 Safe Read</span>'}</span>
      </div>
      ${step.notes ? `<div class="step-node-notes">${escapeHtml(step.notes)}</div>` : ''}
    `;

    return el;
  }

  selectNode(stepId) {
    this.selectedStepId = stepId;
    if (!this.currentPlan) return;

    // Highlight node
    const allNodes = this.container.querySelectorAll('.dag-step-node');
    allNodes.forEach(n => {
      n.style.outline = 'none';
      n.style.boxShadow = '';
    });

    const activeNode = document.getElementById(`node-${stepId}`);
    if (activeNode) {
      activeNode.style.outline = '2px solid var(--accent-cyan)';
      activeNode.style.boxShadow = '0 0 16px var(--accent-cyan-glow)';
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
