/* Tasks Kanban + Calendar Alpine.js component */
function crmTasks() {
  return {
    tasks: [],
    loading: true,
    error: null,
    searchQuery: '',
    calSelectedDate: null,
    showDrawer: false,
    editingTask: null,
    drawerForm: { title: '', description: '', due_date: '', priority: 'medium', contact_id: '', assigned_to_user_id: '' },
    savingTask: false,
    calDays: [],

    async init() {
      this.buildCalDays();
      await this.loadTasks();
    },

    // ── Calendar Strip ───────────────────────────────────────────
    buildCalDays() {
      const days = [];
      const today = new Date();
      today.setHours(0,0,0,0);
      for (let i = -3; i <= 17; i++) {
        const d = new Date(today);
        d.setDate(today.getDate() + i);
        days.push({
          date: d,
          iso: d.toISOString().slice(0, 10),
          dow: d.toLocaleDateString('en', { weekday: 'short' }),
          dom: d.getDate(),
          isToday: i === 0,
        });
      }
      this.calDays = days;
    },

    calDayDots(isoDate) {
      return this.tasks.filter(t => t.due_date === isoDate).length;
    },

    selectCalDay(iso) {
      this.calSelectedDate = this.calSelectedDate === iso ? null : iso;
    },

    // ── Load ─────────────────────────────────────────────────────
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

    // ── Filtering ────────────────────────────────────────────────
    get filteredTasks() {
      let t = this.tasks;
      if (this.calSelectedDate) t = t.filter(x => x.due_date === this.calSelectedDate);
      if (this.searchQuery) {
        const q = this.searchQuery.toLowerCase();
        t = t.filter(x => x.title.toLowerCase().includes(q));
      }
      return t;
    },

    get todoTasks()      { return this.filteredTasks.filter(t => t.status === 'pending' || t.status === 'in_progress'); },
    get doneTasks()      { return this.filteredTasks.filter(t => t.status === 'completed'); },
    get cancelledTasks() { return this.filteredTasks.filter(t => t.status === 'cancelled'); },

    // ── Card Helpers ─────────────────────────────────────────────
    isOverdue(task) {
      if (!task.due_date || task.status === 'completed' || task.status === 'cancelled') return false;
      const d = new Date(task.due_date + 'T00:00:00');
      const today = new Date(); today.setHours(0,0,0,0);
      return d < today;
    },

    formatDue(d) {
      if (!d) return null;
      const dt = new Date(d + 'T00:00:00');
      const today = new Date(); today.setHours(0,0,0,0);
      const diff = Math.round((dt - today) / 86400000);
      if (diff === 0) return 'Today';
      if (diff === 1) return 'Tomorrow';
      if (diff === -1) return 'Yesterday';
      if (diff < 0) return `${Math.abs(diff)}d ago`;
      return dt.toLocaleDateString('en-NZ', { day: 'numeric', month: 'short' });
    },

    priorityClass(p) {
      return { high: 'crm-badge--high', medium: 'crm-badge--medium', low: 'crm-badge--low' }[p] || '';
    },

    statusClass(s) {
      return { pending: 'crm-badge--pending', in_progress: 'crm-badge--in_progress', completed: 'crm-badge--completed', cancelled: 'crm-badge--cancelled' }[s] || '';
    },

    // ── Status transitions ───────────────────────────────────────
    async moveTask(task, newStatus) {
      if (task.status === newStatus) return;
      const prevStatus = task.status;
      task.status = newStatus; // optimistic
      try {
        const { task: updated } = await CRMAPI.updateTask(task.id, { status: newStatus });
        const idx = this.tasks.findIndex(t => t.id === task.id);
        if (idx !== -1) this.tasks[idx] = updated;
      } catch (e) {
        task.status = prevStatus;
        alert(e.message || 'Failed to update task.');
      }
    },

    // ── Drawer ───────────────────────────────────────────────────
    openCreate() {
      this.editingTask = null;
      this.drawerForm = { title: '', description: '', due_date: this.calSelectedDate || '', priority: 'medium', contact_id: '', assigned_to_user_id: '' };
      this.showDrawer = true;
    },

    openEdit(task) {
      this.editingTask = task;
      this.drawerForm = {
        title: task.title,
        description: task.description || '',
        due_date: task.due_date || '',
        priority: task.priority || 'medium',
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
        if (!data.contact_id) delete data.contact_id;
        if (!data.assigned_to_user_id) delete data.assigned_to_user_id;
        if (!data.due_date) delete data.due_date;

        if (this.editingTask) {
          const { task } = await CRMAPI.updateTask(this.editingTask.id, data);
          const idx = this.tasks.findIndex(t => t.id === this.editingTask.id);
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
      if (!confirm(`Delete task "${task.title}"?`)) return;
      try {
        await CRMAPI.deleteTask(task.id);
        this.tasks = this.tasks.filter(t => t.id !== task.id);
      } catch (e) {
        alert(e.message || 'Failed to delete task.');
      }
    },
  };
}
