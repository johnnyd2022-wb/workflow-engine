/* Always-on Core Tasks board and its notification-policy settings. */
(function () {
  'use strict';

  const OPEN = ['pending', 'in_progress'];
  const DEFAULT_LANES = [
    { id: 'todo', title: 'To Do', status: 'pending', custom: false },
    { id: 'in-progress', title: 'In Progress', status: 'in_progress', custom: false },
    { id: 'done', title: 'Done', status: 'completed', custom: false },
    { id: 'cancelled', title: 'Cancelled', status: 'cancelled', custom: false },
  ];

  function isoToday() { return new Date().toISOString().slice(0, 10); }
  function asLocalDate(iso) { return new Date(String(iso) + 'T00:00:00'); }

  window.coreTasksBoard = function () {
    return {
      tasks: [], users: [], lanes: DEFAULT_LANES.slice(), loading: true, error: '',
      searchQuery: '', sourceFilter: 'all', assigneeFilter: '', onlyAssigned: false, selectedDate: '',
      showDrawer: false, showLaneModal: false, editingTask: null, saving: false, draggingTask: null, dragOverLane: '', laneTitle: '',
      form: { title: '', description: '', due_date: '', priority: 'medium', status: 'pending', assigned_to_user_id: '' },

      async init() {
        const params = new URLSearchParams(window.location.search || '');
        if (['core', 'crm'].includes(params.get('source'))) this.sourceFilter = params.get('source');
        await Promise.all([this.loadTasks(), this.loadLanes(), this.loadUsers()]);
      },

      async loadTasks() {
        this.loading = true; this.error = '';
        try {
          const data = await CoreAPI.getTasks();
          this.tasks = (data.tasks || []).map((task) => ({ ...task, key: `${task.source}:${task.id}` }));
        } catch (err) { this.error = err.message || 'Could not load tasks.'; }
        finally { this.loading = false; }
      },

      async loadLanes() {
        this.lanes = DEFAULT_LANES.slice();
        try {
          const data = await CoreAPI.getTaskLanes();
          (data.lanes || []).forEach((lane) => this.lanes.push({ ...lane, custom: true, status: 'pending' }));
        } catch (err) { this.error = this.error || 'Could not load task lanes.'; }
      },

      async loadUsers() {
        try {
          const response = await fetch('/org/users', { credentials: 'include' });
          if (!response.ok) throw new Error('users');
          const data = await response.json();
          this.users = data.users || [];
        } catch (_) { this.users = []; }
      },

      get activeUsers() { return this.users.filter((user) => user.is_active); },
      get upcomingDays() {
        const start = asLocalDate(isoToday()); const days = [];
        for (let index = 0; index < 14; index += 1) {
          const day = new Date(start); day.setDate(start.getDate() + index);
          const iso = day.toISOString().slice(0, 10);
          days.push({ iso, isToday: index === 0, label: day.toLocaleDateString('en-NZ', { weekday: 'short' }), number: day.getDate() });
        }
        return days;
      },
      tasksDueOn(iso) { return this.tasks.filter((task) => task.due_date === iso && OPEN.includes(task.status)).length; },
      get filteredTasks() {
        const query = this.searchQuery.trim().toLowerCase();
        return this.tasks.filter((task) => {
          if (this.sourceFilter !== 'all' && task.source !== this.sourceFilter) return false;
          if (this.assigneeFilter && task.assigned_to_user_id !== this.assigneeFilter) return false;
          if (this.onlyAssigned && !task.assigned_to_user_id) return false;
          if (this.selectedDate && task.due_date !== this.selectedDate) return false;
          return !query || task.title.toLowerCase().includes(query) || String(task.description || '').toLowerCase().includes(query);
        });
      },
      get visibleLanes() { return this.lanes; },
      laneFor(task) {
        if (!task) return 'todo';
        if (!OPEN.includes(task.status)) return DEFAULT_LANES.find((lane) => lane.status === task.status).id;
        if (task.source === 'core' && task.board_lane_id && this.lanes.some((lane) => lane.custom && lane.id === task.board_lane_id)) return task.board_lane_id;
        return task.status === 'in_progress' ? 'in-progress' : 'todo';
      },
      tasksForLane(lane) { return this.filteredTasks.filter((task) => this.laneFor(task) === lane.id); },
      isOverdue(task) { return !!task.due_date && OPEN.includes(task.status) && task.due_date < isoToday(); },
      dueLabel(task) {
        if (!task.due_date) return 'No due date';
        if (this.isOverdue(task)) return `Overdue · ${task.due_date}`;
        if (task.due_date === isoToday()) return 'Due today';
        return `Due ${task.due_date}`;
      },
      openCreate() {
        this.editingTask = null;
        this.form = { title: '', description: '', due_date: this.selectedDate || '', priority: 'medium', status: 'pending', assigned_to_user_id: '' };
        this.showDrawer = true;
      },
      openTask(task) {
        if (!task.editable) { window.location.assign(task.href); return; }
        this.editingTask = task;
        this.form = { title: task.title, description: task.description || '', due_date: task.due_date || '', priority: task.priority || 'medium', status: task.status || 'pending', assigned_to_user_id: task.assigned_to_user_id || '' };
        this.showDrawer = true;
      },
      closeDrawer() { this.showDrawer = false; this.editingTask = null; },
      async saveTask() {
        if (!this.form.title.trim()) return;
        this.saving = true;
        const body = { ...this.form, assigned_to_user_id: this.form.assigned_to_user_id || null, due_date: this.form.due_date || null };
        try {
          if (this.editingTask) {
            const { task } = await CoreAPI.updateTask(this.editingTask.id, body);
            const index = this.tasks.findIndex((row) => row.key === this.editingTask.key);
            if (index >= 0) this.tasks[index] = { ...task, key: `core:${task.id}` };
          } else {
            const { task } = await CoreAPI.createTask(body);
            this.tasks.unshift({ ...task, key: `core:${task.id}` });
          }
          CoreAPI.invalidateSystemFindings(); this.closeDrawer();
        } catch (err) { this.error = err.message || 'Could not save task.'; }
        finally { this.saving = false; }
      },
      async deleteTask() {
        if (!this.editingTask || !window.confirm(`Delete task "${this.editingTask.title}"?`)) return;
        try {
          await CoreAPI.deleteTask(this.editingTask.id);
          this.tasks = this.tasks.filter((task) => task.key !== this.editingTask.key);
          CoreAPI.invalidateSystemFindings(); this.closeDrawer();
        } catch (err) { this.error = err.message || 'Could not delete task.'; }
      },
      openLaneModal() { this.laneTitle = ''; this.showLaneModal = true; },
      async saveLane() {
        const title = this.laneTitle.trim(); if (!title) return;
        try {
          const { lane } = await CoreAPI.createTaskLane({ title });
          this.lanes.push({ ...lane, custom: true, status: 'pending' }); this.showLaneModal = false;
        } catch (err) { this.error = err.message || 'Could not add lane.'; }
      },
      async removeLane(laneId) {
        const lane = this.lanes.find((item) => item.id === laneId);
        if (!lane || !window.confirm(`Delete lane "${lane.title}"? Tasks return to their default lane.`)) return;
        try { await CoreAPI.deleteTaskLane(laneId); await Promise.all([this.loadLanes(), this.loadTasks()]); }
        catch (err) { this.error = err.message || 'Could not delete lane.'; }
      },
      async renameLane(lane) {
        const title = window.prompt('Lane name', lane.title);
        if (title === null || title.trim() === lane.title) return;
        try {
          const { lane: updated } = await CoreAPI.updateTaskLane(lane.id, { title: title.trim() });
          Object.assign(lane, updated);
        } catch (err) { this.error = err.message || 'Could not rename lane.'; }
      },
      async moveLane(lane, direction) {
        const custom = this.lanes.filter((item) => item.custom);
        const index = custom.findIndex((item) => item.id === lane.id);
        const target = index + direction;
        if (index < 0 || target < 0 || target >= custom.length) return;
        [custom[index], custom[target]] = [custom[target], custom[index]];
        try {
          await CoreAPI.reorderTaskLanes(custom.map((item) => item.id));
          await this.loadLanes();
        } catch (err) { this.error = err.message || 'Could not reorder lanes.'; }
      },
      startDrag(task) { if (task.editable) this.draggingTask = task; },
      async dropInLane(lane) {
        const task = this.draggingTask; this.draggingTask = null; this.dragOverLane = '';
        if (!task || !task.editable) return;
        try {
          const laneId = lane.custom ? lane.id : null;
          const { task: placement } = await CoreAPI.assignTaskLane(task.id, laneId);
          task.board_lane_id = placement.board_lane_id;
          const wantedStatus = lane.custom ? 'pending' : lane.status;
          if (task.status !== wantedStatus) {
            const { task: updated } = await CoreAPI.updateTask(task.id, { status: wantedStatus });
            Object.assign(task, updated, { key: `core:${task.id}` });
          }
          CoreAPI.invalidateSystemFindings();
        } catch (err) { this.error = err.message || 'Could not move task.'; }
      },
      openCrmTask() { if (this.editingTask?.href) window.location.assign(this.editingTask.href); },
    };
  };

  window.coreTaskConfiguration = function () {
    return {
      config: { due_notifications_enabled: true, notification_lead_value: 7, notification_lead_unit: 'days' }, error: '', saving: false,
      async init() {
        try { this.config = await CoreAPI.getTaskConfiguration(); }
        catch (err) { this.error = err.message || 'Could not load task settings.'; }
      },
      async save() {
        this.saving = true; this.error = '';
        try {
          this.config.notification_lead_value = Math.max(1, Math.min(3650, Number(this.config.notification_lead_value || 7)));
          this.config = await CoreAPI.updateTaskConfiguration(this.config);
          CoreAPI.invalidateSystemFindings();
        } catch (err) { this.error = err.message || 'Could not save task settings.'; }
        finally { this.saving = false; }
      },
    };
  };
})();
