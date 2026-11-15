(function registerCampaignBrowser() {
  "use strict";

  const storageKey = "pulsar.campaignBrowser.v1";
  const columns = [
    { key: "modified_at", label: "Recorded modified", sortable: true },
    { key: "added_at", label: "Added to campaign", sortable: true },
    { key: "coverage", label: "Information", sortable: false },
  ];
  const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });

  function preferences(value) {
    const saved = value && typeof value === "object" ? value : {};
    return {
      view: saved.view === "gallery" ? "gallery" : "list",
      sort: ["name", "modified_at", "added_at"].includes(saved.sort) ? saved.sort : "name",
      direction: saved.direction === "desc" ? "desc" : "asc",
      columns: Array.isArray(saved.columns)
        ? columns.filter(column => saved.columns.includes(column.key)).map(column => column.key)
        : ["modified_at", "coverage"],
    };
  }

  function sorted(items, key, direction) {
    const sign = direction === "desc" ? -1 : 1;
    return [...items].sort((a, b) => {
      let comparison;
      if (key === "name") {
        comparison = collator.compare(a.name, b.name);
      } else {
        const left = Date.parse(a[key]);
        const right = Date.parse(b[key]);
        const leftMissing = !Number.isFinite(left);
        const rightMissing = !Number.isFinite(right);
        if (leftMissing !== rightMissing) return leftMissing ? 1 : -1;
        comparison = leftMissing ? 0 : left - right;
      }
      return sign * comparison || collator.compare(a.name, b.name)
        || String(a.path || a.name).localeCompare(String(b.path || b.name));
    });
  }

  const component = {
    props: {
      campaigns: { type: Array, default: () => [] },
      selection: { type: Object, default: () => ({}) },
    },
    emits: ["select", "open", "inspect", "details"],
    data() {
      let saved;
      try { saved = JSON.parse(window.localStorage.getItem(storageKey)); } catch (_) { /* Defaults work without storage. */ }
      return { preferences: preferences(saved), columns, expandedCampaigns: {}, expandedDirectories: {} };
    },
    watch: {
      preferences: {
        deep: true,
        handler(value) {
          try { window.localStorage.setItem(storageKey, JSON.stringify(value)); } catch (_) { /* Storage may be disabled. */ }
        },
      },
    },
    computed: {
      visibleColumns() { return this.columns.filter(column => this.preferences.columns.includes(column.key)); },
      orderedCampaigns() {
        const order = items => sorted(items, this.preferences.sort, this.preferences.direction);
        return order(this.campaigns).map(campaign => ({ ...campaign,
          directories: order(campaign.directories).map(directory => ({ ...directory, datasets: order(directory.datasets) })),
        }));
      },
      rows() {
        const rows = [];
        for (const campaign of this.orderedCampaigns) {
          rows.push({ key: campaign.id, kind: "campaign", campaign, item: campaign });
          if (this.expandedCampaigns[campaign.id] === false) continue;
          for (const directory of campaign.directories) {
            const key = this.directoryKey(campaign, directory);
            rows.push({ key, kind: "directory", campaign, directory, item: directory });
            if (!this.expandedDirectories[key]) continue;
            for (const dataset of directory.datasets) {
              rows.push({ key: JSON.stringify([campaign.id, dataset.name]), kind: "file", campaign, directory, item: dataset });
            }
          }
        }
        return rows;
      },
    },
    methods: {
      directoryKey(campaign, directory) { return JSON.stringify([campaign.id, directory.path]); },
      select(row) {
        this.$emit("select", { kind: row.kind, campaign_path: row.campaign.path,
          directory_path: row.directory ? row.directory.path : "",
          dataset_name: row.kind === "file" ? row.item.name : "" });
      },
      isSelected(row) {
        return this.selection.kind === row.kind && this.selection.campaign_path === row.campaign.path
          && (row.kind !== "directory" || this.selection.directory_path === row.directory.path)
          && (row.kind !== "file" || this.selection.dataset_name === row.item.name);
      },
      expanded(row) {
        return row.kind === "campaign" ? this.expandedCampaigns[row.campaign.id] !== false : !!this.expandedDirectories[row.key];
      },
      toggle(row) {
        if (row.kind === "campaign") this.expandedCampaigns[row.campaign.id] = !this.expanded(row);
        else this.expandedDirectories[row.key] = !this.expanded(row);
        this.select(row);
      },
      setSort(key) {
        this.preferences.direction = this.preferences.sort === key
          ? (this.preferences.direction === "asc" ? "desc" : "asc") : (key === "name" ? "asc" : "desc");
        this.preferences.sort = key;
      },
      ariaSort(key) { return this.preferences.sort === key ? (this.preferences.direction === "asc" ? "ascending" : "descending") : "none"; },
      sortArrow(key) { return this.preferences.sort === key ? (this.preferences.direction === "asc" ? " ↑" : " ↓") : ""; },
      date(value) {
        const time = new Date(value);
        return value && Number.isFinite(time.getTime()) ? time.toLocaleString(undefined, {
          year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", timeZoneName: "short",
        }) : "unknown";
      },
      dateTitle(row, key) {
        if (row.kind === "file") return key === "modified_at" ? "Source modification time recorded when packaged" : "Recorded dataset insertion time";
        if (row.kind === "campaign" && key === "added_at") return "A campaign addition date is not inferred from its files";
        return key === "modified_at" ? "Latest recorded BP file modification in this group"
          : "Earliest BP file addition, shown only when all files have recorded addition dates";
      },
      open(row) {
        if (row.kind === "campaign" || (row.kind === "file" && row.item.explorable)) {
          this.$emit("open", { campaign_path: row.campaign.path, dataset_name: row.kind === "file" ? row.item.name : "" });
        }
      },
    },
    template: `
      <div class="pulsar-campaign-browser">
        <div class="pulsar-campaign-toolbar">
          <div class="pulsar-campaign-view-buttons" role="group" aria-label="Campaign view">
            <button type="button" :aria-pressed="preferences.view === 'list'" @click="preferences.view = 'list'">List</button>
            <button type="button" :aria-pressed="preferences.view === 'gallery'" @click="preferences.view = 'gallery'">Gallery</button>
          </div>
          <label>Sort by <select aria-label="Sort campaigns by" :value="preferences.sort" @change="setSort($event.target.value)">
            <option value="name">Name</option><option value="modified_at">Recorded modified</option><option value="added_at">Added to campaign</option>
          </select></label>
          <label>Order <select aria-label="Campaign sort order" v-model="preferences.direction">
            <option value="asc">Ascending</option><option value="desc">Descending</option>
          </select></label>
          <details class="pulsar-campaign-column-menu" v-if="preferences.view === 'list'">
            <summary>Columns</summary><div>
              <label><input type="checkbox" checked disabled> Name</label>
              <label v-for="column in columns" :key="column.key"><input type="checkbox" :value="column.key" v-model="preferences.columns"> {{ column.label }}</label>
            </div>
          </details>
        </div>
        <div class="pulsar-campaign-browser-panes">
          <div class="pulsar-campaign-inventory">
            <table v-if="preferences.view === 'list'" class="pulsar-campaign-list" aria-label="Campaign contents">
              <thead><tr>
                <th :aria-sort="ariaSort('name')"><button type="button" @click="setSort('name')">Name{{ sortArrow('name') }}</button></th>
                <th v-for="column in visibleColumns" :key="column.key" :aria-sort="column.sortable ? ariaSort(column.key) : undefined">
                  <button v-if="column.sortable" type="button" @click="setSort(column.key)">{{ column.label }}{{ sortArrow(column.key) }}</button>
                  <span v-else>{{ column.label }}</span>
                </th>
              </tr></thead>
              <tbody><tr v-for="row in rows" :key="row.key" :class="['pulsar-campaign-list-row', 'is-' + row.kind, {'is-selected': isSelected(row)}]"
                :aria-selected="isSelected(row)" tabindex="0" @click="select(row)" @keydown.enter.self.prevent="select(row)" @keydown.space.self.prevent="select(row)" @dblclick="open(row)">
                <td><div class="pulsar-campaign-list-name">
                  <button v-if="row.kind !== 'file'" type="button" class="pulsar-campaign-disclosure" :aria-expanded="expanded(row)"
                    :aria-label="(expanded(row) ? 'Collapse ' : 'Expand ') + row.item.name" @click.stop="toggle(row)">{{ expanded(row) ? '▾' : '▸' }}</button>
                  <span class="pulsar-campaign-list-label">{{ row.item.label || row.item.name }}</span>
                  <span v-if="row.kind === 'directory' && row.item.datasets.length" class="pulsar-campaign-muted">{{ row.item.datasets.length }} BP {{ row.item.datasets.length === 1 ? 'file' : 'files' }}</span>
                  <span v-if="row.kind === 'campaign' && row.item.error" :title="row.item.error" aria-label="Campaign data loading issue">ⓘ</span>
                  <button v-if="row.kind === 'campaign'" type="button" class="pulsar-campaign-list-open" @click.stop="open(row)">Open</button>
                </div></td>
                <td v-for="column in visibleColumns" :key="column.key" :title="column.sortable ? dateTitle(row, column.key) : ''">
                  <span v-if="column.sortable" class="pulsar-campaign-list-date">{{ row.kind === 'campaign' && column.key === 'added_at' ? '—' : date(row.item[column.key]) }}</span>
                  <span v-else>{{ row.item[column.key] || '—' }}</span>
                </td>
              </tr></tbody>
            </table>
            <div v-else class="pulsar-campaign-gallery-view">
              <details v-for="campaign in orderedCampaigns" :key="campaign.id" :open="expandedCampaigns[campaign.id] !== false"
                @toggle="expandedCampaigns[campaign.id] = $event.target.open" class="pulsar-campaign-section">
                <summary class="pulsar-campaign-summary" @click="select({kind:'campaign', campaign, item:campaign})">
                  <strong>{{ campaign.name }}</strong><span v-if="campaign.error" :title="campaign.error">ⓘ</span>
                  <button type="button" class="pulsar-campaign-list-open" @click.stop="$emit('open', {campaign_path:campaign.path})">Open</button>
                </summary>
                <div class="pulsar-campaign-body">
                  <p v-if="!campaign.directories.length" class="pulsar-campaign-muted">No ADIOS BP files or visualizations</p>
                  <details v-for="directory in campaign.directories" :key="directory.path" class="pulsar-campaign-directory"
                    :open="!!expandedDirectories[directoryKey(campaign,directory)]" @toggle="expandedDirectories[directoryKey(campaign,directory)] = $event.target.open">
                    <summary class="pulsar-campaign-directory-name" @click="select({kind:'directory', campaign, directory, item:directory})">
                      {{ directory.name }}<span v-if="directory.datasets.length" class="pulsar-campaign-directory-coverage">{{ directory.datasets.length }} BP {{ directory.datasets.length === 1 ? 'file' : 'files' }}</span>
                      <span class="pulsar-campaign-directory-coverage">{{ directory.coverage }}</span>
                    </summary>
                    <div class="pulsar-campaign-directory-content">
                      <div v-if="directory.datasets.length" class="pulsar-campaign-bp-files"><h3 class="pulsar-campaign-bp-label">BP files:</h3>
                        <div v-for="dataset in directory.datasets" :key="dataset.name" class="pulsar-campaign-bp-entry">
                          <button type="button" class="pulsar-campaign-bp-file" @click="select({kind:'file', campaign, directory, item:dataset})"
                            @dblclick="open({kind:'file', campaign, item:dataset})">{{ dataset.label }}</button>
                          <span class="pulsar-campaign-added">Modified: {{ date(dataset.modified_at) }}</span>
                          <span v-if="dataset.added_at" class="pulsar-campaign-added">Added: {{ date(dataset.added_at) }}</span>
                          <span class="pulsar-campaign-muted">{{ dataset.coverage }}</span>
                          <button type="button" class="pulsar-campaign-file-details" @click="$emit('details', {campaign_path:campaign.path,dataset_name:dataset.name})">Details</button>
                        </div>
                      </div>
                      <h3 v-if="directory.results.length" class="pulsar-campaign-gallery-heading">Visualizations</h3>
                      <div class="pulsar-campaign-gallery"><button v-for="result in directory.results" :key="result.id" type="button" class="pulsar-campaign-result" @click="$emit('inspect', result.id)">
                        <div class="pulsar-campaign-preview"><span class="pulsar-campaign-placeholder">{{ result.kind }}</span>
                          <img v-if="result.preview" :src="result.preview" :alt="result.title" loading="lazy" onerror="this.style.display='none'">
                        </div><strong>{{ result.title }}</strong><span class="pulsar-campaign-muted">{{ result.caption }}</span>
                      </button></div>
                    </div>
                  </details>
                </div>
              </details>
            </div>
          </div>
          <aside class="pulsar-campaign-selection" aria-label="Selected campaign contents" aria-live="polite"><slot></slot></aside>
        </div>
      </div>`,
  };

  const runtime = { install(app) { app.component("pulsar-campaign-browser", component); } };
  window.pulsarCampaignBrowser = runtime;
})();
