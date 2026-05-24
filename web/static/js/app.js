document.addEventListener('alpine:init', () => {

  // ===== WORKSPACE =====
  Alpine.data('workspace', () => ({
    uploadedFile: null,
    uploadedPreview: null,
    currentTaskId: null,
    selectedSceneId: 0,
    scenes: [],
    platforms: [
      { id: 'taobao', label: '淘宝 800×800', selected: true },
      { id: 'douyin_square', label: '抖音商品卡 800×800', selected: true },
      { id: 'douyin_vertical', label: '抖音竖版 720×960', selected: false },
      { id: 'pinduoduo', label: '拼多多 800×800', selected: true },
      { id: 'jd', label: '京东 800×800', selected: true },
      { id: 'xiaohongshu', label: '小红书 1080×1440', selected: false },
    ],
    processing: false,
    results: [],
    errorMsg: '',

    get allPlatformsSelected() {
      return this.platforms.every(p => p.selected);
    },

    async init() {
      try {
        const r = await fetch('/api/templates');
        const data = await r.json();
        const flat = [];
        for (const [cat, items] of Object.entries(data)) {
          for (const item of items) { flat.push(item); }
        }
        this.scenes = flat;
      } catch (e) {
        console.error('Failed to load scenes:', e);
      }
    },

    handleFile(e) {
      const file = e.target.files[0];
      if (!file) return;
      this.setFile(file);
    },

    handleDrop(e) {
      const file = e.dataTransfer.files[0];
      if (!file || !file.type.startsWith('image/')) return;
      this.setFile(file);
    },

    setFile(file) {
      this.uploadedFile = file;
      this.results = [];
      this.errorMsg = '';
      const reader = new FileReader();
      reader.onload = (ev) => { this.uploadedPreview = ev.target.result; };
      reader.readAsDataURL(file);
    },

    resetAll() {
      this.uploadedFile = null;
      this.uploadedPreview = null;
      this.currentTaskId = null;
      this.selectedSceneId = 0;
      this.results = [];
      this.errorMsg = '';
    },

    toggleAllPlatforms() {
      const val = !this.allPlatformsSelected;
      this.platforms.forEach(p => { p.selected = val; });
    },

    async process() {
      if (!this.uploadedFile || this.processing) return;
      this.processing = true;
      this.errorMsg = '';

      try {
        // Step 1: Remove background
        const fd1 = new FormData();
        fd1.append('file', this.uploadedFile);
        const r1 = await fetch('/api/images/remove-bg', { method: 'POST', body: fd1 });
        if (!r1.ok) {
          const err = await r1.json();
          throw new Error(err.detail || '去背景失败');
        }
        const bgData = await r1.json();
        if (bgData.status === 'failed') throw new Error('去背景处理失败');
        this.currentTaskId = bgData.task_id;

        // Step 2: Apply scene if selected
        let composeTaskId = bgData.task_id;
        if (this.selectedSceneId > 0) {
          const r2 = await fetch('/api/images/apply-scene', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ task_id: bgData.task_id, scene_id: this.selectedSceneId }),
          });
          if (!r2.ok) {
            const err = await r2.json();
            throw new Error(err.detail || '场景合成失败');
          }
          const compData = await r2.json();
          if (compData.status === 'failed') throw new Error('场景合成失败');
          composeTaskId = compData.task_id;
        }

        // Step 3: Multi-platform
        const selectedPlatforms = this.platforms.filter(p => p.selected).map(p => p.id);
        const r3 = await fetch('/api/images/multi-platform', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ task_id: composeTaskId, platforms: selectedPlatforms }),
        });
        if (!r3.ok) {
          const err = await r3.json();
          throw new Error(err.detail || '多平台适配失败');
        }
        const mpData = await r3.json();
        this.results = mpData.results || [];
      } catch (e) {
        this.errorMsg = e.message;
      } finally {
        this.processing = false;
      }
    },

    async downloadAll() {
      for (const r of this.results) {
        try {
          const resp = await fetch(r.url);
          const blob = await resp.blob();
          const a = document.createElement('a');
          a.href = URL.createObjectURL(blob);
          a.download = r.filename;
          a.click();
          URL.revokeObjectURL(a.href);
          await new Promise(resolve => setTimeout(resolve, 300));
        } catch (e) {
          console.error('Download failed:', e);
        }
      }
    },
  }));

  // ===== TASK HISTORY =====
  Alpine.data('taskHistory', () => ({
    tasks: [],
    loading: true,
    searchQuery: '',
    filterType: 'all',
    filterStatus: 'all',
    sortOrder: 'newest',

    get filteredTasks() {
      let result = this.tasks;
      if (this.searchQuery) {
        const q = this.searchQuery.toLowerCase();
        result = result.filter(t => (t.original_filename || '').toLowerCase().includes(q));
      }
      if (this.filterType !== 'all') {
        result = result.filter(t => t.task_type === this.filterType);
      }
      if (this.filterStatus !== 'all') {
        result = result.filter(t => t.status === this.filterStatus);
      }
      result = [...result].sort((a, b) => {
        const da = new Date(a.created_at || 0).getTime();
        const db = new Date(b.created_at || 0).getTime();
        return this.sortOrder === 'newest' ? db - da : da - db;
      });
      return result;
    },

    async init() {
      await this.loadTasks();
    },

    async loadTasks() {
      this.loading = true;
      try {
        const r = await fetch('/api/tasks?limit=50');
        const data = await r.json();
        this.tasks = data.tasks || [];
      } catch (e) {
        console.error('Failed to load tasks:', e);
      } finally {
        this.loading = false;
      }
    },

    async deleteTask(id) {
      if (!confirm('确定删除该任务及所有输出文件？')) return;
      try {
        await fetch(`/api/tasks/${id}`, { method: 'DELETE' });
        this.tasks = this.tasks.filter(t => t.id !== id);
      } catch (e) {
        console.error('Delete failed:', e);
      }
    },

    formatTime(iso) {
      if (!iso) return '-';
      const d = new Date(iso);
      const pad = n => String(n).padStart(2, '0');
      return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
    },
  }));

  // ===== SETTINGS PAGE =====
  Alpine.data('settingsPage', () => ({
    currentTab: 'status',
    showUpload: false,
    templateCount: 0,
    allScenes: [],
    newScene: { name: '', category: 'custom' },
    newSceneFile: null,

    async init() {
      await this.loadScenes();
    },

    async loadScenes() {
      try {
        const r = await fetch('/api/templates');
        const data = await r.json();
        const flat = [];
        for (const [cat, items] of Object.entries(data)) {
          for (const item of items) { flat.push(item); }
        }
        this.allScenes = flat;
        this.templateCount = flat.length;
      } catch (e) {
        console.error('Failed to load scenes:', e);
      }
    },

    handleSceneFile(e) {
      this.newSceneFile = e.target.files[0];
    },

    async uploadScene() {
      if (!this.newScene.name || !this.newSceneFile) return;
      const fd = new FormData();
      fd.append('file', this.newSceneFile);
      fd.append('name', this.newScene.name);
      fd.append('category', this.newScene.category);
      try {
        await fetch('/api/templates', { method: 'POST', body: fd });
        this.showUpload = false;
        this.newScene = { name: '', category: 'custom' };
        this.newSceneFile = null;
        await this.loadScenes();
      } catch (e) {
        console.error('Upload failed:', e);
      }
    },

    async deleteScene(id) {
      if (!confirm('确定删除此场景？')) return;
      try {
        await fetch(`/api/templates/${id}`, { method: 'DELETE' });
        await this.loadScenes();
      } catch (e) {
        console.error('Delete failed:', e);
      }
    },
  }));

});
