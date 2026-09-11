/* Core task board: the CRM calendar interaction, with durable Core layout. */
(function () {
  'use strict';
  const OPEN = ['pending', 'in_progress'];
  const DEFAULT_LANES = [
    { id: 'todo', title: 'To Do', status: 'pending', custom: false, visible: true },
    { id: 'in-progress', title: 'In Progress', status: 'in_progress', custom: false, visible: true },
    { id: 'done', title: 'Done', status: 'completed', custom: false, visible: true },
    { id: 'cancelled', title: 'Cancelled', status: 'cancelled', custom: false, visible: true },
  ];

  window.coreTasksBoard = function () {
    return {
      tasks: [], activeTasks: [], archivedTasks: [], archiveLoaded: false, showArchive: false,
      users: [], lanes: [], config: {}, loading: true, error: '', searchQuery: '', sourceFilter: 'all', assigneeFilter: '', onlyAssigned: false,
      calSelectedDate: null, calVisibleMonthLabel: '', calDays: [], calDragPointerId: null, calDragStartX: 0, calDragStartScrollLeft: 0, calDragActive: false, calSuppressClickUntil: 0, calExtendingBefore: false, calExtendingAfter: false,
      showDrawer: false, showLaneModal: false, showLaneManager: false, editingTask: null, saving: false, laneTitle: '',
      draggingTask: null, dragOverLane: '', draggingLaneId: '', dragOverLaneOrder: '', archiveLoading: false,
      form: { title: '', description: '', due_date: '', priority: 'medium', status: 'pending', assigned_to_user_id: '' },

      async init() {
        if (this._boundToCoreTab) return;
        this._boundToCoreTab = true;
        window.addEventListener('core2:tasks-open', () => { this.loadBoard(); });
        const tab = new URLSearchParams(window.location.search || '').get('tab');
        if (tab === 'tasks') await this.loadBoard();
      },
      async loadBoard() {
        if (this._initialised) return;
        this._initialised = true;
        const params = new URLSearchParams(window.location.search || '');
        if (['core', 'crm'].includes(params.get('source'))) this.sourceFilter = params.get('source');
        this.initCalendarWindow();
        await Promise.all([this.loadConfig(), this.loadLanes(), this.loadUsers(), this.loadTasks('active')]);
        this.applyLanePreferences();
      },
      todayIso() { const d = new Date(); d.setHours(0, 0, 0, 0); return d.toISOString().slice(0, 10); },
      parseIsoDate(iso) { const d = new Date(`${iso}T00:00:00`); d.setHours(0, 0, 0, 0); return d; },
      buildCalDay(dateObj) { const d = new Date(dateObj); d.setHours(0, 0, 0, 0); const iso = d.toISOString().slice(0, 10); return { date: d, iso, dow: d.toLocaleDateString('en', { weekday: 'short' }), dom: d.getDate(), isToday: iso === this.todayIso() }; },
      buildCalDays(start, end) { const days = []; const cursor = new Date(start); const last = new Date(end); cursor.setHours(0, 0, 0, 0); last.setHours(0, 0, 0, 0); while (cursor <= last) { days.push(this.buildCalDay(cursor)); cursor.setDate(cursor.getDate() + 1); } return days; },
      initCalendarWindow(anchorIso) { const anchor = this.parseIsoDate(anchorIso || this.todayIso()); this.calDays = this.buildCalDays(new Date(anchor.getFullYear(), anchor.getMonth(), 1), new Date(anchor.getFullYear(), anchor.getMonth() + 1, 0)); this.$nextTick(() => { this.centerCalendar(); this.updateCalVisibleMonthLabel(); }); },
      centerCalendar() { const strip = this.$refs.calStrip; if (!strip || !this.calDays.length) return; const first = strip.querySelector(`[data-cal-day="${this.calDays[0].iso}"]`); const last = strip.querySelector(`[data-cal-day="${this.calDays[this.calDays.length - 1].iso}"]`); if (!first || !last) return; strip.scrollLeft = Math.max(0, ((first.offsetLeft + last.offsetLeft + last.offsetWidth) / 2) - (strip.clientWidth / 2)); },
      closestVisibleCalDateIso() { const strip = this.$refs.calStrip; if (!strip) return this.calDays[0]?.iso || null; const center = strip.scrollLeft + strip.clientWidth / 2; let best = null; let distance = Infinity; strip.querySelectorAll('[data-cal-day]').forEach((node) => { const next = Math.abs((node.offsetLeft + node.offsetWidth / 2) - center); if (next < distance) { distance = next; best = node.getAttribute('data-cal-day'); } }); return best; },
      updateCalVisibleMonthLabel() { const iso = this.closestVisibleCalDateIso(); this.calVisibleMonthLabel = iso ? this.parseIsoDate(iso).toLocaleDateString('en-NZ', { month: 'long', year: 'numeric' }) : ''; },
      onCalScroll() { this.updateCalVisibleMonthLabel(); const strip = this.$refs.calStrip; if (!strip) return; if (strip.scrollLeft < 260) this.extendCalBeforeMonth(); if (strip.scrollWidth - strip.scrollLeft - strip.clientWidth < 260) this.extendCalAfterMonth(); },
      extendCalBeforeMonth() { if (this.calExtendingBefore || !this.calDays.length) return; this.calExtendingBefore = true; const strip = this.$refs.calStrip; const width = strip?.scrollWidth || 0; const left = strip?.scrollLeft || 0; const first = this.calDays[0].date; this.calDays = this.buildCalDays(new Date(first.getFullYear(), first.getMonth() - 1, 1), new Date(first.getFullYear(), first.getMonth(), 0)).concat(this.calDays); this.$nextTick(() => { const scroller = this.$refs.calStrip; if (scroller) scroller.scrollLeft = left + Math.max(0, scroller.scrollWidth - width); this.calExtendingBefore = false; this.updateCalVisibleMonthLabel(); }); },
      extendCalAfterMonth() { if (this.calExtendingAfter || !this.calDays.length) return; this.calExtendingAfter = true; const last = this.calDays[this.calDays.length - 1].date; this.calDays = this.calDays.concat(this.buildCalDays(new Date(last.getFullYear(), last.getMonth() + 1, 1), new Date(last.getFullYear(), last.getMonth() + 2, 0))); this.$nextTick(() => { this.calExtendingAfter = false; this.updateCalVisibleMonthLabel(); }); },
      onCalPointerDown(event) { if (event.pointerType === 'mouse' && event.button !== 0) return; const strip = this.$refs.calStrip; if (!strip) return; this.calDragActive = true; this.calDragPointerId = event.pointerId; this.calDragStartX = event.clientX; this.calDragStartScrollLeft = strip.scrollLeft; if (strip.setPointerCapture) strip.setPointerCapture(event.pointerId); },
      onCalPointerMove(event) { if (!this.calDragActive || event.pointerId !== this.calDragPointerId) return; const strip = this.$refs.calStrip; if (!strip) return; const delta = event.clientX - this.calDragStartX; if (Math.abs(delta) > 6) this.calSuppressClickUntil = Date.now() + 180; strip.scrollLeft = this.calDragStartScrollLeft - delta; },
      onCalPointerUp(event) { if (event.pointerId !== this.calDragPointerId) return; const strip = this.$refs.calStrip; if (strip?.releasePointerCapture) { try { strip.releasePointerCapture(event.pointerId); } catch (_) {} } this.calDragActive = false; this.calDragPointerId = null; },
      calDayDots(iso) { return this.tasks.filter((task) => task.due_date === iso && OPEN.includes(task.status)).length; },
      selectCalDay(iso) { if (Date.now() >= this.calSuppressClickUntil) this.calSelectedDate = this.calSelectedDate === iso ? null : iso; },

      async loadConfig() { try { this.config = await CoreAPI.getTaskConfiguration(); } catch (err) { this.error = err.message || 'Could not load task settings.'; } },
      async loadTasks(archive) { this.loading = archive === 'active'; try { const data = await CoreAPI.getTasks({ archive }); const rows = (data.tasks || []).map((task) => ({ ...task, key: `${task.source}:${task.id}` })); if (archive === 'archived') { this.archivedTasks = rows; this.archiveLoaded = true; } else this.activeTasks = rows; this.tasks = this.showArchive ? this.archivedTasks : this.activeTasks; } catch (err) { this.error = err.message || 'Could not load tasks.'; } finally { if (archive === 'active') this.loading = false; } },
      async loadLanes() { try { const data = await CoreAPI.getTaskLanes(); this.lanes = DEFAULT_LANES.map((lane) => ({ ...lane })).concat((data.lanes || []).map((lane) => ({ ...lane, custom: true, status: 'pending', visible: true }))); } catch (err) { this.error = this.error || 'Could not load task lanes.'; this.lanes = DEFAULT_LANES.map((lane) => ({ ...lane })); } },
      async loadUsers() { try { const response = await fetch('/org/users', { credentials: 'include' }); if (!response.ok) throw new Error('users'); this.users = (await response.json()).users || []; } catch (_) { this.users = []; } },
      applyLanePreferences() { const hidden = new Set(this.config.hidden_default_lanes || []); this.lanes.forEach((lane) => { lane.visible = lane.custom || !hidden.has(lane.id); }); const saved = this.config.lane_order || []; const ordered = saved.map((id) => this.lanes.find((lane) => lane.id === id)).filter(Boolean); this.lanes = ordered.concat(this.lanes.filter((lane) => !saved.includes(lane.id))); },
      async persistLayout() { try { const custom = this.lanes.filter((lane) => lane.custom).map((lane) => lane.id); if (custom.length) await CoreAPI.reorderTaskLanes(custom); this.config = await CoreAPI.updateTaskConfiguration({ lane_order: this.lanes.map((lane) => lane.id), hidden_default_lanes: this.lanes.filter((lane) => !lane.custom && !lane.visible).map((lane) => lane.id) }); } catch (err) { this.error = err.message || 'Could not save lane layout.'; } },
      get activeUsers() { return this.users.filter((user) => user.is_active); },
      get filteredTasks() { const query = this.searchQuery.trim().toLowerCase(); return this.tasks.filter((task) => (!this.sourceFilter || this.sourceFilter === 'all' || task.source === this.sourceFilter) && (!this.assigneeFilter || task.assigned_to_user_id === this.assigneeFilter) && (!this.onlyAssigned || task.assigned_to_user_id) && (!this.calSelectedDate || task.due_date === this.calSelectedDate) && (!query || task.title.toLowerCase().includes(query) || String(task.description || '').toLowerCase().includes(query))); },
      get visibleLanes() { return this.lanes.filter((lane) => lane.visible); },
      laneFor(task) { if (!task) return 'todo'; if (!OPEN.includes(task.status)) return task.status === 'completed' ? 'done' : 'cancelled'; if (task.source === 'core' && task.board_lane_id && this.lanes.some((lane) => lane.custom && lane.id === task.board_lane_id)) return task.board_lane_id; return task.status === 'in_progress' ? 'in-progress' : 'todo'; },
      tasksForLane(lane) { return this.filteredTasks.filter((task) => this.laneFor(task) === lane.id); },
      laneHeaderClass(lane) { return lane.custom ? 'core-tasks__lane-header--custom' : `core-tasks__lane-header--${lane.id}`; },
      isOverdue(task) { return !!task.due_date && OPEN.includes(task.status) && task.due_date < this.todayIso(); },
      dueLabel(task) { if (!task.due_date) return 'No due date'; if (this.isOverdue(task)) return `Overdue · ${task.due_date}`; if (task.due_date === this.todayIso()) return 'Due today'; return `Due ${task.due_date}`; },
      async toggleArchive() { if (this.showArchive) { this.showArchive = false; this.tasks = this.activeTasks; return; } this.archiveLoading = true; if (!this.archiveLoaded) await this.loadTasks('archived'); this.showArchive = true; this.tasks = this.archivedTasks; this.archiveLoading = false; },

      openCreate() { this.editingTask = null; this.form = { title: '', description: '', due_date: this.calSelectedDate || '', priority: 'medium', status: 'pending', assigned_to_user_id: '' }; this.showDrawer = true; },
      openTask(task) { if (!task.editable) { window.location.assign(task.href); return; } this.editingTask = task; this.form = { title: task.title, description: task.description || '', due_date: task.due_date || '', priority: task.priority || 'medium', status: task.status || 'pending', assigned_to_user_id: task.assigned_to_user_id || '' }; this.showDrawer = true; },
      closeDrawer() { this.showDrawer = false; this.editingTask = null; },
      async saveTask() { if (!this.form.title.trim()) return; this.saving = true; const body = { ...this.form, assigned_to_user_id: this.form.assigned_to_user_id || null, due_date: this.form.due_date || null }; try { if (this.editingTask) { const { task } = await CoreAPI.updateTask(this.editingTask.id, body); const idx = this.activeTasks.findIndex((row) => row.key === this.editingTask.key); if (idx >= 0) this.activeTasks[idx] = { ...task, key: `core:${task.id}` }; } else { const { task } = await CoreAPI.createTask(body); this.activeTasks.unshift({ ...task, key: `core:${task.id}` }); } this.tasks = this.showArchive ? this.archivedTasks : this.activeTasks; CoreAPI.invalidateSystemFindings(); this.closeDrawer(); } catch (err) { this.error = err.message || 'Could not save task.'; } finally { this.saving = false; } },
      async deleteTask() { if (!this.editingTask || !window.confirm(`Delete task "${this.editingTask.title}"?`)) return; try { await CoreAPI.deleteTask(this.editingTask.id); this.activeTasks = this.activeTasks.filter((task) => task.key !== this.editingTask.key); this.archivedTasks = this.archivedTasks.filter((task) => task.key !== this.editingTask.key); this.tasks = this.showArchive ? this.archivedTasks : this.activeTasks; CoreAPI.invalidateSystemFindings(); this.closeDrawer(); } catch (err) { this.error = err.message || 'Could not delete task.'; } },
      openLaneModal() { this.laneTitle = ''; this.showLaneModal = true; }, openLaneManager() { this.showLaneManager = true; },
      async saveLane() { const title = this.laneTitle.trim(); if (!title) return; try { const { lane } = await CoreAPI.createTaskLane({ title }); this.lanes.push({ ...lane, custom: true, status: 'pending', visible: true }); await this.persistLayout(); this.showLaneModal = false; } catch (err) { this.error = err.message || 'Could not add lane.'; } },
      async removeLane(laneId) { const lane = this.lanes.find((item) => item.id === laneId); if (!lane || !window.confirm(`Delete lane "${lane.title}"? Tasks return to their default lane.`)) return; try { await CoreAPI.deleteTaskLane(laneId); this.lanes = this.lanes.filter((item) => item.id !== laneId); await this.persistLayout(); await this.loadTasks(this.showArchive ? 'archived' : 'active'); } catch (err) { this.error = err.message || 'Could not delete lane.'; } },
      async renameLane(lane) { const title = window.prompt('Lane name', lane.title); if (title === null || title.trim() === lane.title) return; try { const { lane: updated } = await CoreAPI.updateTaskLane(lane.id, { title: title.trim() }); Object.assign(lane, updated); } catch (err) { this.error = err.message || 'Could not rename lane.'; } },
      async toggleDefaultLane(laneId) { const lane = this.lanes.find((item) => item.id === laneId); if (!lane) return; lane.visible = !lane.visible; await this.persistLayout(); },
      startLaneDrag(lane, event) { if (this.draggingTask || event.target.closest('button')) { event.preventDefault(); return; } this.draggingLaneId = lane.id; event.dataTransfer.effectAllowed = 'move'; }, endLaneDrag() { this.draggingLaneId = ''; this.dragOverLaneOrder = ''; }, setLaneDragOver(laneId) { if (this.draggingLaneId && this.draggingLaneId !== laneId) this.dragOverLaneOrder = laneId; }, clearLaneDragOver(laneId) { if (this.dragOverLaneOrder === laneId) this.dragOverLaneOrder = ''; },
      async dropLaneBefore(targetId) { const sourceId = this.draggingLaneId; this.endLaneDrag(); if (!sourceId || sourceId === targetId) return; const source = this.lanes.findIndex((lane) => lane.id === sourceId); const target = this.lanes.findIndex((lane) => lane.id === targetId); if (source < 0 || target < 0) return; const [lane] = this.lanes.splice(source, 1); this.lanes.splice(source < target ? target - 1 : target, 0, lane); await this.persistLayout(); },
      startTaskDrag(task) { if (task.editable) { this.draggingTask = task; this.draggingLaneId = ''; } }, endTaskDrag() { this.draggingTask = null; this.dragOverLane = ''; }, setTaskDragOver(laneId) { if (this.draggingTask) this.dragOverLane = laneId; }, clearTaskDragOver(laneId) { if (this.dragOverLane === laneId) this.dragOverLane = ''; },
      async dropInLane(lane) { const task = this.draggingTask; this.endTaskDrag(); if (!task || !task.editable) return; try { const laneId = lane.custom ? lane.id : null; const { task: placement } = await CoreAPI.assignTaskLane(task.id, laneId); task.board_lane_id = placement.board_lane_id; const status = lane.custom ? 'pending' : lane.status; if (task.status !== status) { const { task: updated } = await CoreAPI.updateTask(task.id, { status }); Object.assign(task, updated, { key: `core:${task.id}` }); } CoreAPI.invalidateSystemFindings(); } catch (err) { this.error = err.message || 'Could not move task.'; } },
      openCrmTask() { if (this.editingTask?.href) window.location.assign(this.editingTask.href); },
    };
  };

  window.coreTaskConfiguration = function () {
    return {
      config: { due_notifications_enabled: true, notification_lead_value: 7, notification_lead_unit: 'days', done_archive_value: 1, done_archive_unit: 'weeks' }, error: '', saving: false,
      async init() { try { this.config = await CoreAPI.getTaskConfiguration(); } catch (err) { this.error = err.message || 'Could not load task settings.'; } },
      async save() { this.saving = true; this.error = ''; try { this.config.notification_lead_value = Math.max(1, Math.min(3650, Number(this.config.notification_lead_value || 7))); this.config.done_archive_value = Math.max(1, Math.min(3650, Number(this.config.done_archive_value || 1))); this.config = await CoreAPI.updateTaskConfiguration(this.config); CoreAPI.invalidateSystemFindings(); } catch (err) { this.error = err.message || 'Could not save task settings.'; } finally { this.saving = false; } },
    };
  };
})();
