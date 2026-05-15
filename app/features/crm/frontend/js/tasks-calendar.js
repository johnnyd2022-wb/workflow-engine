/* Tasks Kanban + Calendar Alpine.js component */
function crmTasks() {
  const LANE_STORAGE_KEY = 'crm_task_lanes_v2';
  const LANE_ASSIGNMENT_STORAGE_KEY = 'crm_task_lane_assignments_v1';
  const DEFAULT_LANE_IDS = {
    todo: 'lane-todo',
    inProgress: 'lane-in-progress',
    done: 'lane-completed',
    cancelled: 'lane-cancelled',
  };
  const OPEN_STATUSES = ['pending', 'in_progress'];

  function defaultLanes() {
    return [
      { id: DEFAULT_LANE_IDS.todo, title: 'To Do', status_mode: 'pending', deletable: false },
      { id: DEFAULT_LANE_IDS.inProgress, title: 'In Progress', status_mode: 'in_progress', deletable: false },
      { id: DEFAULT_LANE_IDS.done, title: 'Done', status_mode: 'completed', deletable: false },
      { id: DEFAULT_LANE_IDS.cancelled, title: 'Cancelled', status_mode: 'cancelled', deletable: false },
    ];
  }

  return {
    tasks: [],
    customers: [],
    operators: [],
    operatorFilter: '',
    onlyAssigned: false,
    lanes: defaultLanes(),
    laneAssignments: {},
    loading: true,
    error: null,
    searchQuery: '',
    calSelectedDate: null,
    calVisibleMonthLabel: '',
    showArchivedCancelled: false,
    taskDoneArchiveDays: 7,
    showLaneModal: false,
    laneDraft: { title: '' },
    activeLaneId: null,
    isMobileView: false,
    draggingTaskId: null,
    dragOverLaneId: null,
    dragSuppressUntil: 0,
    showDrawer: false,
    editingTask: null,
    drawerForm: {
      title: '',
      description: '',
      due_date: '',
      priority: 'medium',
      status: 'pending',
      contact_id: '',
      assigned_to_user_id: '',
    },
    savingTask: false,
    calDays: [],
    wasMobileView: null,
    calDragPointerId: null,
    calDragStartX: 0,
    calDragStartScrollLeft: 0,
    calDragActive: false,
    calSuppressClickUntil: 0,
    calExtendingBefore: false,
    calExtendingAfter: false,

    async init() {
      CRMAPI.ensureBackButton('/crm');
      this.loadLanes();
      this.loadLaneAssignments();
      this.syncViewport();
      window.addEventListener('resize', () => { this.syncViewport(); });
      this.initCalendarWindow();
      await Promise.all([this.loadOperators(), this.loadTasks(), this.loadCustomers(), this.loadTraceabilityConfig()]);
      this.pruneLaneAssignments();
      this.openTaskFromQueryString();
    },

    syncViewport() {
      const nextMobile = window.innerWidth <= 768;
      const changed = this.wasMobileView !== null && this.wasMobileView !== nextMobile;
      this.isMobileView = nextMobile;
      this.wasMobileView = nextMobile;
      if (changed) {
        const anchorIso = this.calSelectedDate || this.closestVisibleCalDateIso() || this.todayIso();
        this.initCalendarWindow(anchorIso);
      }
    },

    todayIso() {
      const d = new Date();
      d.setHours(0, 0, 0, 0);
      return d.toISOString().slice(0, 10);
    },

    parseIsoDate(iso) {
      const d = new Date(`${iso}T00:00:00`);
      d.setHours(0, 0, 0, 0);
      return d;
    },

    buildCalDay(dateObj) {
      const d = new Date(dateObj);
      d.setHours(0, 0, 0, 0);
      const iso = d.toISOString().slice(0, 10);
      return {
        date: d,
        iso,
        dow: d.toLocaleDateString('en', { weekday: 'short' }),
        dom: d.getDate(),
        isToday: iso === this.todayIso(),
      };
    },

    monthBounds(dateObj) {
      const d = new Date(dateObj);
      d.setHours(0, 0, 0, 0);
      const start = new Date(d.getFullYear(), d.getMonth(), 1);
      const end = new Date(d.getFullYear(), d.getMonth() + 1, 0);
      return { start, end };
    },

    buildCalDays(startDate, endDate) {
      const days = [];
      const cursor = new Date(startDate);
      cursor.setHours(0, 0, 0, 0);
      const last = new Date(endDate);
      last.setHours(0, 0, 0, 0);
      while (cursor <= last) {
        days.push(this.buildCalDay(cursor));
        cursor.setDate(cursor.getDate() + 1);
      }
      return days;
    },

    initCalendarWindow(anchorIso = null) {
      const anchor = anchorIso ? this.parseIsoDate(anchorIso) : this.parseIsoDate(this.todayIso());
      const { start, end } = this.monthBounds(anchor);
      this.calDays = this.buildCalDays(start, end);
      this.$nextTick(() => {
        this.centerCurrentMonthInView();
        this.updateCalVisibleMonthLabel();
      });
    },

    centerCurrentMonthInView() {
      const strip = this.$refs.calStrip;
      if (!strip || !this.calDays.length) return;
      const firstIso = this.calDays[0].iso;
      const lastIso = this.calDays[this.calDays.length - 1].iso;
      const first = strip.querySelector(`[data-cal-day="${firstIso}"]`);
      const last = strip.querySelector(`[data-cal-day="${lastIso}"]`);
      if (!first || !last) return;
      const monthStart = first.offsetLeft;
      const monthEnd = last.offsetLeft + last.offsetWidth;
      const midpoint = monthStart + ((monthEnd - monthStart) / 2);
      strip.scrollLeft = Math.max(0, midpoint - (strip.clientWidth / 2));
    },

    scrollDateIntoView(iso, align = 'center') {
      const strip = this.$refs.calStrip;
      if (!strip) return;
      const target = strip.querySelector(`[data-cal-day="${iso}"]`);
      if (!target) return;
      const left = target.offsetLeft - Math.max(0, (strip.clientWidth - target.offsetWidth) / (align === 'center' ? 2 : 1));
      strip.scrollLeft = Math.max(0, left);
    },

    closestVisibleCalDateIso() {
      const strip = this.$refs.calStrip;
      if (!strip) return this.calDays[0]?.iso || null;
      const center = strip.scrollLeft + (strip.clientWidth / 2);
      const cards = strip.querySelectorAll('[data-cal-day]');
      let bestIso = null;
      let bestDist = Infinity;
      cards.forEach((node) => {
        const nodeCenter = node.offsetLeft + (node.offsetWidth / 2);
        const dist = Math.abs(nodeCenter - center);
        if (dist < bestDist) {
          bestDist = dist;
          bestIso = node.getAttribute('data-cal-day');
        }
      });
      return bestIso;
    },

    updateCalVisibleMonthLabel() {
      const iso = this.closestVisibleCalDateIso();
      if (!iso) {
        this.calVisibleMonthLabel = '';
        return;
      }
      const d = this.parseIsoDate(iso);
      this.calVisibleMonthLabel = d.toLocaleDateString('en-NZ', { month: 'long', year: 'numeric' });
    },

    onCalScroll() {
      this.updateCalVisibleMonthLabel();
      const strip = this.$refs.calStrip;
      if (!strip) return;
      const threshold = 260;
      if (strip.scrollLeft < threshold) this.extendCalBeforeMonth();
      if ((strip.scrollWidth - (strip.scrollLeft + strip.clientWidth)) < threshold) this.extendCalAfterMonth();
    },

    extendCalBeforeMonth() {
      if (this.calExtendingBefore || !this.calDays.length) return;
      this.calExtendingBefore = true;
      const strip = this.$refs.calStrip;
      const prevScrollWidth = strip ? strip.scrollWidth : 0;
      const prevScrollLeft = strip ? strip.scrollLeft : 0;
      const first = this.calDays[0].date;
      const start = new Date(first.getFullYear(), first.getMonth() - 1, 1);
      const end = new Date(first.getFullYear(), first.getMonth(), 0);
      const prepend = this.buildCalDays(start, end);
      this.calDays = prepend.concat(this.calDays);
      this.$nextTick(() => {
        const scroller = this.$refs.calStrip;
        if (scroller) {
          const delta = scroller.scrollWidth - prevScrollWidth;
          scroller.scrollLeft = prevScrollLeft + Math.max(0, delta);
        }
        this.calExtendingBefore = false;
        this.updateCalVisibleMonthLabel();
      });
    },

    extendCalAfterMonth() {
      if (this.calExtendingAfter || !this.calDays.length) return;
      this.calExtendingAfter = true;
      const last = this.calDays[this.calDays.length - 1].date;
      const start = new Date(last.getFullYear(), last.getMonth() + 1, 1);
      const end = new Date(last.getFullYear(), last.getMonth() + 2, 0);
      const append = this.buildCalDays(start, end);
      this.calDays = this.calDays.concat(append);
      this.$nextTick(() => {
        this.calExtendingAfter = false;
        this.updateCalVisibleMonthLabel();
      });
    },

    onCalPointerDown(event) {
      if (event.pointerType === 'mouse' && event.button !== 0) return;
      const strip = this.$refs.calStrip;
      if (!strip) return;
      this.calDragActive = true;
      this.calDragPointerId = event.pointerId;
      this.calDragStartX = event.clientX;
      this.calDragStartScrollLeft = strip.scrollLeft;
      if (strip.setPointerCapture) strip.setPointerCapture(event.pointerId);
    },

    onCalPointerMove(event) {
      if (!this.calDragActive) return;
      if (this.calDragPointerId !== null && event.pointerId !== this.calDragPointerId) return;
      const strip = this.$refs.calStrip;
      if (!strip) return;
      const delta = event.clientX - this.calDragStartX;
      if (Math.abs(delta) > 6) this.calSuppressClickUntil = Date.now() + 180;
      strip.scrollLeft = this.calDragStartScrollLeft - delta;
    },

    onCalPointerUp(event) {
      if (this.calDragPointerId !== null && event.pointerId !== this.calDragPointerId) return;
      const strip = this.$refs.calStrip;
      if (strip && strip.releasePointerCapture && this.calDragPointerId !== null) {
        try { strip.releasePointerCapture(this.calDragPointerId); } catch (_) {}
      }
      this.calDragActive = false;
      this.calDragPointerId = null;
    },

    calDayDots(isoDate) {
      return this.tasks.filter((t) => t.due_date === isoDate).length;
    },

    selectCalDay(iso) {
      if (Date.now() < this.calSuppressClickUntil) return;
      this.calSelectedDate = this.calSelectedDate === iso ? null : iso;
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

    openTaskFromQueryString() {
      const params = new URLSearchParams(window.location.search || '');
      const taskId = params.get('task_id');
      if (!taskId) return;
      const task = this.tasks.find((t) => t.id === taskId);
      if (task) this.openEdit(task);
    },

    get filteredTasks() {
      let t = this.tasks;
      if (this.calSelectedDate) t = t.filter((x) => x.due_date === this.calSelectedDate);
      if (this.searchQuery) {
        const q = this.searchQuery.toLowerCase();
        t = t.filter((x) => x.title.toLowerCase().includes(q));
      }
      if (this.onlyAssigned) t = t.filter((x) => !!x.assigned_to_user_id);
      if (this.operatorFilter) t = t.filter((x) => x.assigned_to_user_id === this.operatorFilter);
      return t;
    },

    get customLaneCount() {
      return this.lanes.filter((lane) => lane.deletable).length;
    },

    get canAddCustomLane() {
      return this.customLaneCount < 1;
    },

    loadLanes() {
      const base = defaultLanes();
      this.lanes = base.slice();
      const seenDefault = new Set(base.map((lane) => lane.id));
      try {
        const raw = localStorage.getItem(LANE_STORAGE_KEY);
        if (!raw) return;
        const parsed = JSON.parse(raw);
        if (!Array.isArray(parsed)) return;
        let customAdded = 0;
        parsed.forEach((lane) => {
          if (!lane || typeof lane !== 'object') return;
          const id = String(lane.id || '').trim();
          const title = String(lane.title || '').trim();
          if (!id || !title || seenDefault.has(id)) return;
          if (customAdded >= 1) return;
          this.lanes.push({
            id,
            title,
            status_mode: 'custom',
            deletable: true,
          });
          customAdded += 1;
        });
      } catch (_) {}
      if (!this.activeLaneId || !this.lanes.some((lane) => lane.id === this.activeLaneId)) {
        this.activeLaneId = this.lanes[0]?.id || null;
      }
    },

    persistLanes() {
      try {
        const custom = this.lanes.filter((lane) => lane.deletable);
        localStorage.setItem(LANE_STORAGE_KEY, JSON.stringify(custom));
      } catch (_) {}
    },

    loadLaneAssignments() {
      try {
        const raw = localStorage.getItem(LANE_ASSIGNMENT_STORAGE_KEY);
        const parsed = raw ? JSON.parse(raw) : {};
        this.laneAssignments = parsed && typeof parsed === 'object' ? parsed : {};
      } catch (_) {
        this.laneAssignments = {};
      }
    },

    persistLaneAssignments() {
      try {
        localStorage.setItem(LANE_ASSIGNMENT_STORAGE_KEY, JSON.stringify(this.laneAssignments));
      } catch (_) {}
    },

    pruneLaneAssignments() {
      const taskIds = new Set(this.tasks.map((t) => t.id));
      const laneIds = new Set(this.lanes.map((l) => l.id));
      Object.keys(this.laneAssignments).forEach((taskId) => {
        const laneId = this.laneAssignments[taskId];
        if (!taskIds.has(taskId) || !laneIds.has(laneId)) delete this.laneAssignments[taskId];
      });
      this.persistLaneAssignments();
    },

    openLaneModal() {
      if (!this.canAddCustomLane) return;
      this.laneDraft = { title: '' };
      this.showLaneModal = true;
    },

    closeLaneModal() {
      this.showLaneModal = false;
    },

    saveLane() {
      const title = (this.laneDraft.title || '').trim();
      if (!title) return;
      if (!this.canAddCustomLane) return;
      const exists = this.lanes.some((lane) => lane.title.toLowerCase() === title.toLowerCase());
      if (exists) {
        alert('A lane with this name already exists.');
        return;
      }
      this.lanes.push({
        id: `lane-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
        title,
        status_mode: 'custom',
        deletable: true,
      });
      this.activeLaneId = this.lanes[this.lanes.length - 1].id;
      this.persistLanes();
      this.closeLaneModal();
    },

    removeLane(laneId) {
      const lane = this.lanes.find((x) => x.id === laneId);
      if (!lane || !lane.deletable) return;
      if (!window.confirm(`Delete lane "${lane.title}"?`)) return;
      this.lanes = this.lanes.filter((x) => x.id !== laneId);
      Object.keys(this.laneAssignments).forEach((taskId) => {
        if (this.laneAssignments[taskId] === laneId) delete this.laneAssignments[taskId];
      });
      if (!this.lanes.some((x) => x.id === this.activeLaneId)) {
        this.activeLaneId = this.lanes[0]?.id || null;
      }
      this.persistLanes();
      this.persistLaneAssignments();
    },

    get visibleLanes() {
      if (this.isMobileView) {
        return this.lanes.filter((lane) => lane.id === this.activeLaneId);
      }
      return this.lanes;
    },

    laneHeaderClass(lane) {
      const mode = lane.status_mode;
      if (mode === 'completed') return 'crm-kanban-header--done';
      if (mode === 'cancelled') return 'crm-kanban-header--cancelled';
      if (mode === 'in_progress') return 'crm-kanban-header--inprogress';
      return 'crm-kanban-header--todo';
    },

    defaultLaneForStatus(status) {
      if (status === 'completed') return DEFAULT_LANE_IDS.done;
      if (status === 'cancelled') return DEFAULT_LANE_IDS.cancelled;
      if (status === 'in_progress') return DEFAULT_LANE_IDS.inProgress;
      return DEFAULT_LANE_IDS.todo;
    },

    laneForTask(task) {
      if (!task) return DEFAULT_LANE_IDS.todo;
      if (!OPEN_STATUSES.includes(task.status)) return this.defaultLaneForStatus(task.status);
      const assignedLaneId = this.laneAssignments[task.id];
      if (assignedLaneId && this.lanes.some((lane) => lane.id === assignedLaneId && lane.status_mode === 'custom')) {
        return assignedLaneId;
      }
      return this.defaultLaneForStatus(task.status);
    },

    tasksForLane(lane) {
      return this.filteredTasks.filter((task) => {
        if (task.status === 'completed' && !this.showArchivedCancelled && this.isArchivedCompleted(task)) return false;
        if (task.status === 'cancelled' && !this.showArchivedCancelled && this.isArchivedCancelled(task)) return false;
        return this.laneForTask(task) === lane.id;
      });
    },

    isOverdue(task) {
      if (!task.due_date || task.status === 'completed' || task.status === 'cancelled') return false;
      const d = new Date(task.due_date + 'T00:00:00');
      const today = new Date(); today.setHours(0, 0, 0, 0);
      return d < today;
    },

    formatDue(d) {
      if (!d) return null;
      const dt = new Date(d + 'T00:00:00');
      const today = new Date(); today.setHours(0, 0, 0, 0);
      const diff = Math.round((dt - today) / 86400000);
      if (diff === 0) return 'Today';
      if (diff === 1) return 'Tomorrow';
      if (diff === -1) return 'Yesterday';
      if (diff < 0) return `${Math.abs(diff)}d ago`;
      return dt.toLocaleDateString('en-NZ', { day: 'numeric', month: 'short' });
    },

    formatStatus(status) {
      return (status || '').replace('_', ' ');
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

    isArchivedCancelled(task) {
      if (!task || task.status !== 'cancelled') return false;
      const ts = task.updated_at || task.completed_at || task.created_at;
      if (!ts) return false;
      const dt = new Date(ts);
      if (Number.isNaN(dt.getTime())) return false;
      return (Date.now() - dt.getTime()) >= 3 * 24 * 60 * 60 * 1000;
    },

    isArchivedCompleted(task) {
      if (!task || task.status !== 'completed') return false;
      const ts = task.completed_at || task.updated_at || task.created_at;
      if (!ts) return false;
      const dt = new Date(ts);
      if (Number.isNaN(dt.getTime())) return false;
      const days = Math.min(90, Math.max(1, Number(this.taskDoneArchiveDays || 7)));
      return (Date.now() - dt.getTime()) >= days * 24 * 60 * 60 * 1000;
    },

    priorityClass(p) {
      return { high: 'crm-badge--high', medium: 'crm-badge--medium', low: 'crm-badge--low' }[p] || '';
    },

    statusClass(s) {
      return { pending: 'crm-badge--pending', in_progress: 'crm-badge--in_progress', completed: 'crm-badge--completed', cancelled: 'crm-badge--cancelled' }[s] || '';
    },

    taskCardStyle(task) {
      return task.status === 'cancelled' ? 'opacity:.6;' : (task.status === 'completed' ? 'opacity:.75;' : '');
    },

    taskTitleStyle(task) {
      if (task.status === 'cancelled') return 'text-decoration:line-through;';
      if (task.status === 'completed') return 'text-decoration:line-through; opacity:.7;';
      return '';
    },

    handleCardClick(task) {
      if (Date.now() < this.dragSuppressUntil) return;
      this.openEdit(task);
    },

    startDragTask(task) {
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
        this.laneAssignments[task.id] = lane.id;
        this.persistLaneAssignments();
        if (!OPEN_STATUSES.includes(task.status)) {
          await this.moveTask(task, 'pending');
        }
        return;
      }

      delete this.laneAssignments[task.id];
      this.persistLaneAssignments();
      const targetStatus = lane.status_mode;
      await this.moveTask(task, targetStatus);
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

    openCreate() {
      this.editingTask = null;
      this.drawerForm = {
        title: '',
        description: '',
        due_date: this.calSelectedDate || '',
        priority: 'medium',
        status: 'pending',
        contact_id: '',
        assigned_to_user_id: '',
      };
      this.showDrawer = true;
    },

    openEdit(task) {
      this.editingTask = task;
      this.drawerForm = {
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
        this.pruneLaneAssignments();
        this.closeDrawer();
      } catch (e) {
        alert(e.message || 'Failed to save task.');
      } finally {
        this.savingTask = false;
      }
    },

    async deleteTask(task) {
      if (!confirm(`Delete task "${task.title}"?`)) return;
      try {
        await CRMAPI.deleteTask(task.id);
        this.tasks = this.tasks.filter((t) => t.id !== task.id);
        delete this.laneAssignments[task.id];
        this.persistLaneAssignments();
      } catch (e) {
        alert(e.message || 'Failed to delete task.');
      }
    },
  };
}
