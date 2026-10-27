/* Sales tasks: the follow-ups for customers, as a board, a due list or a week (Alpine.js). */
function crmTasks() {
  const DEFAULT_LANE_IDS = {
    todo: 'lane-todo',
    inProgress: 'lane-in-progress',
    done: 'lane-completed',
    cancelled: 'lane-cancelled',
  };
  const OPEN_STATUSES = ['pending', 'in_progress'];
  const FINISHED_LANE = { id: 'finished', title: 'Finished', status_mode: 'completed', deletable: false };
  const STYLE_KEY = 'tasks-style';
  const DAY_MS = 86400000;

  function defaultLanes() {
    return [
      { id: DEFAULT_LANE_IDS.todo, title: 'To do', status_mode: 'pending', deletable: false },
      { id: DEFAULT_LANE_IDS.inProgress, title: 'In progress', status_mode: 'in_progress', deletable: false },
    ];
  }

  // A local calendar date as YYYY-MM-DD. toISOString() gives the UTC date, which in New Zealand
  // is the day before until 1pm, so due dates landed on the wrong day.
  function localIso(d) {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  }

  function parseIso(iso) {
    const d = new Date(`${iso}T00:00:00`);
    d.setHours(0, 0, 0, 0);
    return d;
  }

  function todayDate() {
    const d = new Date();
    d.setHours(0, 0, 0, 0);
    return d;
  }

  function daysUntil(iso) {
    return Math.round((parseIso(iso) - todayDate()) / DAY_MS);
  }

  function priorityRank(task) {
    return { high: 0, medium: 1, low: 2 }[task.priority] ?? 1;
  }

  function byDue(a, b) {
    if (a.due_date && b.due_date && a.due_date !== b.due_date) return a.due_date < b.due_date ? -1 : 1;
    if (!!a.due_date !== !!b.due_date) return a.due_date ? -1 : 1;
    return priorityRank(a) - priorityRank(b);
  }

  return {
    tasks: [],
    customers: [],
    operators: [],
    me: '',
    operatorFilter: '',
    typeFilter: '',
    tastingsEnabled: false,
    tastingDraftFresh: true,
    lanes: defaultLanes(),
    loading: true,
    error: null,
    searchQuery: '',
    showFinished: false,
    taskDoneArchiveDays: 7,
    showLaneModal: false,
    laneDraft: { title: '' },
    activeLaneId: DEFAULT_LANE_IDS.todo,
    draggingTaskId: null,
    dragOverLaneId: null,
    dragSuppressUntil: 0,
    showDrawer: false,
    editingTask: null,
    drawerForm: {
      task_type: 'general',
      title: '',
      description: '',
      due_date: '',
      priority: 'medium',
      status: 'pending',
      contact_id: '',
      assigned_to_user_id: '',
    },
    savingTask: false,
    weekOffset: 0,
    style: '1',

    // Alpine calls init() itself; the template must not call it again (it did, and every
    // request went out twice).
    async init() {
      this.me = this.$el.dataset.me || '';
      this.tastingsEnabled = this.$el.dataset.tastingsEnabled === 'true';
      // A direct view link takes priority over the remembered choice; Board is the default.
      const params = new URLSearchParams(window.location.search || '');
      const requestedType = params.get('type') || '';
      this.typeFilter = this.validTypes.includes(requestedType) ? requestedType : '';
      const asked = ({ board: '1', list: '2', week: '3' })[params.get('view')] || params.get('style');
      let kept = null;
      try { kept = window.localStorage.getItem(STYLE_KEY); } catch (_) { /* private mode */ }
      this.style = ['1', '2', '3'].includes(asked) ? asked : (['1', '2', '3'].includes(kept) ? kept : '1');
      await Promise.all([this.loadLanes(), this.loadOperators(), this.loadTasks(), this.loadCustomers(), this.loadTraceabilityConfig()]);
      await this.openTaskFromQueryString();
    },

    // Switching views keeps the current filters, tasks and unsaved drawer fields.
    setStyle(style) {
      if (!['1', '2', '3'].includes(style)) return;
      this.style = style;
      try { window.localStorage.setItem(STYLE_KEY, style); } catch (_) { /* private mode */ }
      const url = new URL(window.location.href);
      url.searchParams.set('view', ({ '1': 'board', '2': 'list', '3': 'week' })[style]);
      url.searchParams.delete('style');
      window.history.replaceState(window.history.state, '', url);
    },

    async loadOperators() {
      try {
        const data = await CRMAPI.getOrgUsers();
        this.operators = data?.users || [];
      } catch (e) {
        this.operators = [];
      }
    },

    async loadTasks() {
      this.loading = true;
      this.error = null;
      try {
        const data = await CRMAPI.getTasks({});
        this.tasks = data.tasks || [];
      } catch (e) {
        this.error = e.message || 'Failed to load tasks.';
      } finally {
        this.loading = false;
      }
    },

    async loadCustomers() {
      try {
        const data = await CRMAPI.getCustomers({ page: 1, page_size: 200, sort_by: 'name', sort_dir: 'asc' });
        this.customers = data?.customers || [];
      } catch (_) {
        this.customers = [];
      }
    },

    async loadTraceabilityConfig() {
      try {
        const cfg = await CRMAPI.getTraceabilityConfig();
        this.taskDoneArchiveDays = Math.min(90, Math.max(1, Number(cfg?.task_done_archive_days || 7)));
      } catch (_) {
        this.taskDoneArchiveDays = 7;
      }
    },

    async openTaskFromQueryString() {
      const params = new URLSearchParams(window.location.search || '');
      const taskId = params.get('task_id');
      // "New task" on the Sales overview lands here with the form already open.
      if (!taskId && params.get('new') === '1') { this.openCreate(); return; }
      if (!taskId) return;
      const task = this.tasks.find((t) => t.id === taskId);
      if (task) this.openEdit(task);
      else {
        try {
          const result = await fetch('/api/crm/tasks/' + encodeURIComponent(taskId), { credentials: 'same-origin', headers: { Accept: 'application/json' } });
          if (!result.ok) throw new Error('Task unavailable');
          const response = await result.json();
          if (response.task) this.openEdit(response.task);
        } catch (_) { this.error = 'That task is unavailable. It may require an active subscription or different access.'; }
      }
    },

    // ── What is shown ──

    get filtersOn() {
      return !!(this.searchQuery || this.operatorFilter || this.typeFilter);
    },

    clearFilters() {
      this.searchQuery = '';
      this.operatorFilter = '';
      this.typeFilter = ''; this.rememberType();
    },

    get filteredTasks() {
      let t = this.tasks;
      if (this.typeFilter) t = t.filter((task) => (task.task_type || 'general') === this.typeFilter);
      if (this.searchQuery) {
        const q = this.searchQuery.toLowerCase();
        t = t.filter((x) => [x.title, x.tasting_venue].filter(Boolean).join(' ').toLowerCase().includes(q) || (x.contact_id && this.customerName(x.contact_id).toLowerCase().includes(q)));
      }
      if (this.operatorFilter === '__mine') t = t.filter((x) => x.assigned_to_user_id === this.me);
      else if (this.operatorFilter === '__none') t = t.filter((x) => !x.assigned_to_user_id);
      else if (this.operatorFilter) t = t.filter((x) => x.assigned_to_user_id === this.operatorFilter);
      return t;
    },

    get openTasks() {
      return this.filteredTasks.filter((t) => OPEN_STATUSES.includes(t.status)).sort(byDue);
    },

    // Finished in the last few days (Sales settings: "archive done tasks after"); older ones
    // stay on the customer's page.
    get finishedTasks() {
      const when = (t) => t.completed_at || t.updated_at || t.created_at || '';
      const since = Date.now() - this.taskDoneArchiveDays * DAY_MS;
      return this.filteredTasks
        .filter((t) => !OPEN_STATUSES.includes(t.status) && (!when(t) || new Date(when(t)).getTime() >= since))
        .sort((a, b) => (when(a) < when(b) ? 1 : -1));
    },

    get overdueTasks() {
      return this.openTasks.filter((t) => t.due_date && daysUntil(t.due_date) < 0);
    },

    // Style 3's tray: overdue from before Monday (this week's own late tasks stay on their day).
    get overdueBeforeWeek() {
      const monday = todayDate();
      monday.setDate(monday.getDate() - ((monday.getDay() + 6) % 7));
      const start = localIso(monday);
      return this.overdueTasks.filter((t) => t.due_date < start);
    },

    get undatedTasks() {
      return this.openTasks.filter((t) => !t.due_date);
    },

    get summaryLine() {
      if (this.loading) return 'Follow-ups for your customers, and who is doing them.';
      const open = this.openTasks;
      const late = this.overdueTasks.length;
      const today = open.filter((t) => t.due_date && daysUntil(t.due_date) === 0).length;
      const parts = [`${open.length} open`];
      if (late) parts.push(`${late} overdue`);
      if (today) parts.push(`${today} due today`);
      return parts.join(' · ');
    },

    isFinished(task) {
      return !OPEN_STATUSES.includes(task.status);
    },

    // Style 1: open lanes, then the finished rail.
    get boardLanes() {
      return this.lanes.concat([FINISHED_LANE]);
    },

    // Style 2: grouped by when it is due.
    get dueGroups() {
      const groups = [
        { key: 'overdue', title: 'Overdue', tasks: [] },
        { key: 'today', title: 'Today', tasks: [] },
        { key: 'tomorrow', title: 'Tomorrow', tasks: [] },
        { key: 'week', title: 'This week', tasks: [] },
        { key: 'later', title: 'Later', tasks: [] },
        { key: 'none', title: 'No date', tasks: [] },
      ];
      const at = Object.fromEntries(groups.map((g) => [g.key, g]));
      this.openTasks.forEach((task) => {
        if (!task.due_date) { at.none.tasks.push(task); return; }
        const n = daysUntil(task.due_date);
        if (n < 0) at.overdue.tasks.push(task);
        else if (n === 0) at.today.tasks.push(task);
        else if (n === 1) at.tomorrow.tasks.push(task);
        else if (n <= 6) at.week.tasks.push(task);
        else at.later.tasks.push(task);
      });
      if (this.showFinished) groups.push({ key: 'finished', title: 'Finished', tasks: this.finishedTasks });
      return groups.filter((g) => g.tasks.length);
    },

    // Style 3: Monday to Sunday of the chosen week.
    get weekDays() {
      const start = todayDate();
      start.setDate(start.getDate() - ((start.getDay() + 6) % 7) + this.weekOffset * 7);
      const today = localIso(todayDate());
      const shown = this.showFinished ? this.openTasks.concat(this.finishedTasks) : this.openTasks;
      return Array.from({ length: 7 }, (_, i) => {
        const d = new Date(start);
        d.setDate(start.getDate() + i);
        const iso = localIso(d);
        return {
          iso,
          dow: d.toLocaleDateString('en-NZ', { weekday: 'short' }),
          dom: d.getDate(),
          long: d.toLocaleDateString('en-NZ', { weekday: 'long', day: 'numeric', month: 'long' }),
          isToday: iso === today,
          isPast: iso < today,
          tasks: shown.filter((t) => t.due_date === iso),
        };
      });
    },

    get weekLabel() {
      const days = this.weekDays;
      const first = parseIso(days[0].iso);
      const last = parseIso(days[6].iso);
      const range = `${first.getDate()} ${first.toLocaleDateString('en-NZ', { month: 'short' })} – ${last.getDate()} ${last.toLocaleDateString('en-NZ', { month: 'short' })}`;
      if (this.weekOffset === 0) return `This week · ${range}`;
      if (this.weekOffset === 1) return `Next week · ${range}`;
      if (this.weekOffset === -1) return `Last week · ${range}`;
      return range;
    },

    get validTypes() { return ['general', 'call', 'email'].concat(this.tastingsEnabled ? ['tasting'] : []); },

    rememberType() {
      const url = new URL(window.location.href);
      if (this.typeFilter) url.searchParams.set('type', this.typeFilter); else url.searchParams.delete('type');
      window.history.replaceState(window.history.state, '', url);
    },

    typeWords(task) {
      if (task.tasting_id) {
        const state = { planned: 'Planned', dispatched: 'Stock out', completed: 'Completed', cancelled: 'Cancelled' }[task.tasting_status] || 'Tasting';
        const time = task.tasting_starts_at ? new Intl.DateTimeFormat('en-NZ', { timeZone: 'Pacific/Auckland', hour: 'numeric', minute: '2-digit' }).format(new Date(task.tasting_starts_at)) : '';
        return ['Tasting', state, time, task.tasting_venue].filter(Boolean).join(' · ');
      }
      return ({ call: 'Call', email: 'Email' })[task.task_type] || '';
    },

    tastingWorkspace() {
      if (!this.tastingsEnabled) return null;
      if (window.__tastingsInit) window.__tastingsInit();
      const workspace = document.querySelector('[data-tastings-root]');
      return workspace?._tastings || null;
    },

    openTastingStock() { this.tastingWorkspace()?.stock(); },

    changeTaskType() {
      if (this.drawerForm.task_type !== 'tasting' || this.editingTask) return;
      const workspace = this.tastingWorkspace();
      if (!workspace) { this.error = 'Tasting details are still loading. Please try again.'; this.drawerForm.task_type = 'general'; return; }
      this.showDrawer = false;
      workspace.create({ ...this.drawerForm }, this.tastingDraftFresh);
      this.tastingDraftFresh = false;
    },

    restoreTastingDraft(draft) {
      this.ensureCustomerOptionForTask(draft);
      if (draft.assigned_to_user_id && !this.operators.some((user) => user.id === draft.assigned_to_user_id)) {
        this.operators.push({ id: draft.assigned_to_user_id, display_name: draft.assigned_to_name || 'Selected rep' });
      }
      const { contact_name, contact_email, contact_phone, assigned_to_name, ...fields } = draft;
      this.drawerForm = { ...this.drawerForm, ...fields };
      this.showDrawer = true;
    },

    // ── Words on a card or row ──

    dueWords(task) {
      if (task.status === 'cancelled') return 'Cancelled';
      if (task.status === 'completed') {
        const at = task.completed_at || task.updated_at;
        if (!at) return 'Done';
        const n = Math.round((todayDate() - parseIso(localIso(new Date(at)))) / DAY_MS);
        return n <= 0 ? 'Done today' : (n === 1 ? 'Done yesterday' : `Done ${n} days ago`);
      }
      if (!task.due_date) return 'No date';
      const n = daysUntil(task.due_date);
      if (n < 0) return n === -1 ? '1 day overdue' : `${-n} days overdue`;
      if (n === 0) return 'Today';
      if (n === 1) return 'Tomorrow';
      const d = parseIso(task.due_date);
      if (n <= 6) return d.toLocaleDateString('en-NZ', { weekday: 'long' });
      return d.toLocaleDateString('en-NZ', { day: 'numeric', month: 'short' });
    },

    dueClass(task) {
      if (this.isFinished(task) || !task.due_date) return 'tasks-due--quiet';
      const n = daysUntil(task.due_date);
      if (n < 0) return 'tasks-due--late';
      if (n === 0) return 'tasks-due--today';
      return '';
    },

    whoLine(task) {
      return [task.contact_id ? this.customerName(task.contact_id) : '', task.assigned_to_user_id ? this.assigneeName(task.assigned_to_user_id) : '']
        .filter(Boolean).join(' · ');
    },

    pickLane(lane) {
      this.activeLaneId = lane.id;
      if (lane.id === 'finished') this.showFinished = true;
    },

    taskMeta(task) {
      return [this.whoLine(task), this.stageWords(task)].filter(Boolean).join(' · ');
    },

    stageWords(task) {
      if (this.isFinished(task)) return '';
      const lane = task.board_lane_id && this.lanes.find((l) => l.id === task.board_lane_id && l.status_mode === 'custom');
      if (lane) return lane.title;
      return task.status === 'in_progress' ? 'In progress' : '';
    },

    assigneeName(userId) {
      const u = this.operators.find((x) => x.id === userId);
      return u ? (u.display_name || u.email || 'Assigned') : 'Assigned';
    },

    customerName(contactId) {
      const c = this.customers.find((x) => x.id === contactId);
      if (c) return c.name || 'Customer';
      const task = this.tasks.find((x) => x.contact_id === contactId);
      return task?.contact_name || 'Customer';
    },

    selectedDrawerCustomer() {
      const contactId = this.drawerForm.contact_id || '';
      if (!contactId) return null;
      const c = this.customers.find((x) => x.id === contactId);
      if (c) return c;
      if (this.editingTask && this.editingTask.contact_id === contactId) {
        return {
          id: contactId,
          name: this.editingTask.contact_name || 'Customer',
          email_address: this.editingTask.contact_email || '',
          phone_number: this.editingTask.contact_phone || '',
        };
      }
      return null;
    },

    contactLine() {
      const c = this.selectedDrawerCustomer();
      if (!c) return '';
      const person = `${c.first_name || ''} ${c.last_name || ''}`.trim();
      const parts = [person, c.email_address || c.contact_email, c.phone_number || c.contact_phone].filter(Boolean);
      return parts.length ? parts.join(' · ') : 'No contact details on file';
    },

    ensureCustomerOptionForTask(task) {
      const contactId = String(task?.contact_id || '').trim();
      if (!contactId) return;
      const exists = this.customers.some((c) => String(c.id || '').trim() === contactId);
      if (exists) return;

      this.customers.push({
        id: contactId,
        name: task.contact_name || 'Customer',
        first_name: '',
        last_name: '',
        email_address: task.contact_email || '',
        phone_number: task.contact_phone || '',
      });
    },

    // ── Lanes ──

    // Builds the list, then assigns it once: two loads in flight can't interleave their lanes.
    async loadLanes() {
      const lanes = defaultLanes();
      try {
        const data = await CRMAPI.getTaskLanes();
        (data?.lanes || []).forEach((lane) => {
          const id = String(lane?.id || '').trim();
          const title = String(lane?.title || '').trim();
          if (!id || !title) return;
          lanes.push({
            id,
            title,
            status_mode: 'custom',
            deletable: true,
          });
        });
      } catch (_) {}
      this.lanes = lanes;
      if (!this.activeLaneId || !this.boardLanes.some((lane) => lane.id === this.activeLaneId)) {
        this.activeLaneId = this.lanes[0]?.id || null;
      }
    },

    openLaneModal() {
      this.laneDraft = { title: '' };
      this.showLaneModal = true;
    },

    closeLaneModal() {
      this.showLaneModal = false;
    },

    async saveLane() {
      const title = (this.laneDraft.title || '').trim();
      if (!title) return;
      const exists = this.boardLanes.some((lane) => lane.title.toLowerCase() === title.toLowerCase());
      if (exists) {
        alert('A lane with this name already exists.');
        return;
      }
      try {
        const { lane } = await CRMAPI.createTaskLane({ title });
        this.lanes.push({ ...lane, status_mode: 'custom', deletable: true });
        this.activeLaneId = lane.id;
        this.closeLaneModal();
      } catch (e) { alert(e.message || 'Failed to add lane.'); }
    },

    async removeLane(laneId) {
      const lane = this.lanes.find((x) => x.id === laneId);
      if (!lane || !lane.deletable) return;
      if (!window.confirm(`Delete lane "${lane.title}"?`)) return;
      try {
        await CRMAPI.deleteTaskLane(laneId);
        await Promise.all([this.loadLanes(), this.loadTasks()]);
      } catch (e) { alert(e.message || 'Failed to delete lane.'); }
    },

    async renameLane(lane) {
      const title = window.prompt('Lane name', lane.title);
      if (title === null || title.trim() === lane.title) return;
      try {
        const { lane: updated } = await CRMAPI.updateTaskLane(lane.id, { title: title.trim() });
        Object.assign(lane, updated);
      } catch (e) { alert(e.message || 'Failed to rename lane.'); }
    },

    async moveLane(lane, direction) {
      const custom = this.lanes.filter((item) => item.status_mode === 'custom');
      const index = custom.findIndex((item) => item.id === lane.id);
      const target = index + direction;
      if (index < 0 || target < 0 || target >= custom.length) return;
      [custom[index], custom[target]] = [custom[target], custom[index]];
      try {
        await CRMAPI.reorderTaskLanes(custom.map((item) => item.id));
        await this.loadLanes();
      } catch (e) { alert(e.message || 'Failed to reorder lanes.'); }
    },

    defaultLaneForStatus(status) {
      return status === 'in_progress' ? DEFAULT_LANE_IDS.inProgress : DEFAULT_LANE_IDS.todo;
    },

    laneForTask(task) {
      if (!OPEN_STATUSES.includes(task.status)) return FINISHED_LANE.id;
      const assignedLaneId = task.board_lane_id;
      if (assignedLaneId && this.lanes.some((lane) => lane.id === assignedLaneId && lane.status_mode === 'custom')) {
        return assignedLaneId;
      }
      return this.defaultLaneForStatus(task.status);
    },

    tasksForLane(lane) {
      if (lane.id === FINISHED_LANE.id) return this.finishedTasks;
      return this.openTasks.filter((task) => this.laneForTask(task) === lane.id);
    },

    // ── Moving and finishing ──

    handleCardClick(task) {
      if (Date.now() < this.dragSuppressUntil) return;
      this.openEdit(task);
    },

    startDragTask(task) {
      if (task.tasting_id) return;
      this.draggingTaskId = task?.id || null;
      this.dragSuppressUntil = Date.now() + 200;
    },

    endDragTask() {
      this.dragOverLaneId = null;
      this.dragSuppressUntil = Date.now() + 200;
      window.setTimeout(() => { this.draggingTaskId = null; }, 0);
    },

    setDragOverLane(laneId) {
      if (!this.draggingTaskId) return;
      this.dragOverLaneId = laneId;
    },

    clearDragOverLane(laneId) {
      if (this.dragOverLaneId === laneId) this.dragOverLaneId = null;
    },

    async dropTaskToLane(lane) {
      const taskId = this.draggingTaskId;
      this.dragOverLaneId = null;
      this.draggingTaskId = null;
      if (!taskId) return;
      const task = this.tasks.find((x) => x.id === taskId);
      if (!task) return;

      if (lane.status_mode === 'custom') {
        try {
          const { task: updated } = await CRMAPI.assignTaskLane(task.id, lane.id);
          task.board_lane_id = updated.board_lane_id;
        } catch (e) { alert(e.message || 'Failed to move task.'); return; }
        if (!OPEN_STATUSES.includes(task.status)) {
          await this.moveTask(task, 'pending');
        }
        return;
      }

      try {
        const { task: updated } = await CRMAPI.assignTaskLane(task.id, null);
        task.board_lane_id = updated.board_lane_id;
      } catch (e) { alert(e.message || 'Failed to move task.'); return; }
      await this.moveTask(task, lane.status_mode);
    },

    async toggleDone(task) {
      if (task.tasting_id) { this.tastingWorkspace()?.detail(task.tasting_id); return; }
      await this.moveTask(task, this.isFinished(task) ? 'pending' : 'completed');
    },

    async moveTask(task, newStatus) {
      if (task.status === newStatus) return;
      const prevStatus = task.status;
      task.status = newStatus;
      try {
        const { task: updated } = await CRMAPI.updateTask(task.id, { status: newStatus });
        const idx = this.tasks.findIndex((t) => t.id === task.id);
        if (idx !== -1) this.tasks[idx] = updated;
      } catch (e) {
        task.status = prevStatus;
        alert(e.message || 'Failed to update task.');
      }
    },

    // ── The drawer ──

    openCreate(dueIso = '') {
      this.editingTask = null;
      this.tastingDraftFresh = true;
      this.drawerForm = {
        task_type: this.typeFilter || 'general',
        title: '',
        description: '',
        due_date: dueIso || '',
        priority: 'medium',
        status: 'pending',
        contact_id: '',
        assigned_to_user_id: '',
      };
      this.showDrawer = true;
      if (this.drawerForm.task_type === 'tasting') this.changeTaskType();
    },

    openEdit(task) {
      if (task.tasting_id) { this.tastingWorkspace()?.detail(task.tasting_id); return; }
      this.ensureCustomerOptionForTask(task);
      this.editingTask = task;
      this.drawerForm = {
        task_type: task.task_type || 'general',
        title: task.title,
        description: task.description || '',
        due_date: task.due_date || '',
        priority: task.priority || 'medium',
        status: task.status || 'pending',
        contact_id: task.contact_id || '',
        assigned_to_user_id: task.assigned_to_user_id || '',
      };
      this.showDrawer = true;
    },

    closeDrawer() { this.showDrawer = false; this.editingTask = null; },

    async saveTask() {
      if (!this.drawerForm.title.trim()) return;
      this.savingTask = true;
      try {
        const data = { ...this.drawerForm };
        const normaliseOptionalId = (value) => {
          const raw = String(value == null ? '' : value).trim().toLowerCase();
          return (raw && raw !== 'null' && raw !== 'none') ? String(value).trim() : null;
        };
        data.contact_id = normaliseOptionalId(data.contact_id);
        data.assigned_to_user_id = normaliseOptionalId(data.assigned_to_user_id);
        if (this.editingTask && !data.contact_id) data.contact_id = null;
        if (!this.editingTask && !data.contact_id) delete data.contact_id;
        if (this.editingTask && !data.assigned_to_user_id) data.assigned_to_user_id = null;
        if (!this.editingTask && !data.assigned_to_user_id) delete data.assigned_to_user_id;
        if (!data.due_date) delete data.due_date;

        if (this.editingTask) {
          const { task } = await CRMAPI.updateTask(this.editingTask.id, data);
          const idx = this.tasks.findIndex((t) => t.id === this.editingTask.id);
          if (idx !== -1) this.tasks[idx] = task;
        } else {
          const { task } = await CRMAPI.createTask(data);
          this.tasks.unshift(task);
        }
        this.closeDrawer();
      } catch (e) {
        alert(e.message || 'Failed to save task.');
      } finally {
        this.savingTask = false;
      }
    },

    async deleteTask(task) {
      if (task.tasting_id) { this.tastingWorkspace()?.detail(task.tasting_id); return; }
      if (!confirm(`Delete task "${task.title}"?`)) return;
      try {
        await CRMAPI.deleteTask(task.id);
        this.tasks = this.tasks.filter((t) => t.id !== task.id);
        if (this.editingTask && this.editingTask.id === task.id) this.closeDrawer();
      } catch (e) {
        alert(e.message || 'Failed to delete task.');
      }
    },
  };
}
