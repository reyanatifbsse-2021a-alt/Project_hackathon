/**
 * AegisRuntime - Enhanced Interactive DAG & Step Pipeline Visualizer
 * Visualizes multi-step dependency graphs, runtime interventions, and branch isolation.
 */

class DagVisualizer {
  constructor(containerId, onNodeSelected) {
    this.container = document.getElementById(containerId);
    this.onNodeSelected = onNodeSelected;
    this.currentPlan = null;
    this.selectedStepId = null;
  }

  async render(plan, animate = false) {
    this.currentPlan = plan;
    if (!this.container) return;
    this.container.innerHTML = '';

    if (!plan || !plan.steps || plan.steps.length === 0) {
      this.container.innerHTML = `
        <div style="text-align: center; color: var(--text-dim); padding: 4rem 1rem;">
          <svg style="width: 56px; height: 56px; margin-bottom: 1rem; fill: currentColor; opacity: 0.6;" viewBox="0 0 24 24">
            <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/>
          </svg>
          <div style="font-weight: 700; font-size: 1.1rem; color: var(--text-main);">Execution Pipeline Standby</div>
          <div style="font-size: 0.825rem; margin-top: 0.35rem; color: var(--text-muted);">Select any scenario preset above or type a natural language prompt to begin.</div>
        </div>
      `;
      return;
    }

    // Execution Summary Banner
    const summaryCard = document.createElement('div');
    summaryCard.className = 'glass-panel';
    summaryCard.style.padding = '0.85rem 1.35rem';
    summaryCard.style.marginBottom = '1.25rem';
    summaryCard.style.background = 'rgba(12, 20, 39, 0.95)';

    const isFullSuccess = plan.status === 'COMPLETED_SUCCESSFULLY';
    const isPartial = plan.status === 'PARTIALLY_COMPLETED_CONTINUED';
    const borderColor = isFullSuccess ? 'var(--accent-emerald)' : (isPartial ? 'var(--accent-cyan)' : 'var(--accent-ruby)');
    summaryCard.style.borderLeft = `5px solid ${borderColor}`;

    summaryCard.innerHTML = `
      <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 0.75rem;">
        <div>
          <div style="display: flex; align-items: center; gap: 0.5rem;">
            <span style="font-weight: 800; font-size: 0.875rem; color: ${borderColor};">${escapeHtml(plan.status.replace(/_/g, ' '))}</span>
            <span style="font-size: 0.75rem; color: var(--text-dim); font-family: var(--font-mono);">ID: ${escapeHtml(plan.task_id)}</span>
          </div>
          <div style="color: var(--text-muted); font-size: 0.8rem; margin-top: 0.25rem; line-height: 1.35;">${escapeHtml(plan.summary || '')}</div>
        </div>
        <div style="display: flex; gap: 0.85rem; font-family: var(--font-mono); font-size: 0.775rem;">
          <span style="color: var(--accent-emerald); font-weight: 700;">✔ ${plan.completed_steps_count || 0} Executed</span>
          <span style="color: var(--accent-ruby); font-weight: 700;">🛡 ${plan.blocked_steps_count || 0} Intercepted</span>
          <span style="color: var(--accent-amber); font-weight: 700;">⏸ ${plan.paused_steps_count || 0} Isolated</span>
        </div>
      </div>
    `;
    this.container.appendChild(summaryCard);

    // Render Steps in DAG Sequence
    const stepsList = document.createElement('div');
    stepsList.style.display = 'flex';
    stepsList.style.flexDirection = 'column';
    stepsList.style.gap = '1.15rem';

    plan.steps.forEach((step, index) => {
      const nodeEl = this.createStepNodeElement(step, index);
      stepsList.appendChild(nodeEl);
    });

    this.container.appendChild(stepsList);

    // If animate flag is set, run sequential highlight sweep
    if (animate) {
      for (let i = 0; i < plan.steps.length; i++) {
        const s = plan.steps[i];
        const el = document.getElementById(`node-${s.step_id}`);
        if (el) {
          el.style.transform = 'scale(1.02)';
          await new Promise(r => setTimeout(r, 120));
          el.style.transform = '';
        }
      }
    }

    // Auto-select priority step: first blocked or held step, else first step
    const priorityStep = plan.steps.find(s => s.status === 'BLOCKED' || s.status === 'HELD_FOR_REVIEW') || plan.steps[0];
    if (priorityStep) {
      this.selectNode(priorityStep.step_id);
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
      badgeLabel = 'EXECUTED (ALLOW)';
      badgeIcon = '✔';
    } else if (step.status === 'BLOCKED') {
      badgeClass = 'badge-blocked';
      badgeLabel = 'BLOCKED (INTERCEPTED)';
      badgeIcon = '🛡 ✖';
    } else if (step.status === 'HELD_FOR_REVIEW') {
      badgeClass = 'badge-held';
      badgeLabel = 'HELD FOR CLEARANCE';
      badgeIcon = '⚠ 👤';
    } else if (step.status === 'PAUSED_DEPENDENCY') {
      badgeClass = 'badge-paused';
      badgeLabel = 'BRANCH ISOLATED';
      badgeIcon = '⏸';
    }

    const hasDeps = step.dependencies && step.dependencies.length > 0;
    const depsInfo = hasDeps
      ? `<span style="color: var(--text-dim); font-size: 0.725rem; font-family: var(--font-mono); background: rgba(0,0,0,0.3); padding: 0.15rem 0.5rem; border-radius: 4px;">↳ Depends on: [${step.dependencies.join(', ')}]</span>`
      : `<span style="color: var(--accent-cyan); font-size: 0.725rem; font-family: var(--font-mono); background: rgba(0, 245, 255, 0.08); padding: 0.15rem 0.5rem; border-radius: 4px;">⚡ Independent Safe Branch</span>`;

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
        <span>🔧 Tool: <strong style="color: var(--text-main); font-family: var(--font-mono);">${escapeHtml(toolName)}</strong></span>
        <span>${isProtected ? '<strong style="color: var(--accent-amber);">🔒 Protected Tool (PoA Required)</strong>' : '<span style="color: var(--accent-emerald);">🔓 Safe Read-Only Tool</span>'}</span>
        ${step.verification_result ? `<span style="color: var(--text-dim);">Policy: <strong style="color: var(--accent-cyan);">${escapeHtml(step.verification_result.policy_id)}</strong></span>` : ''}
      </div>
      ${step.notes ? `<div class="step-node-notes">${escapeHtml(step.notes)}</div>` : ''}
    `;

    return el;
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
