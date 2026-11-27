// Numeric settings only. The host owns simulation, rendering and save state.
export function createParameterLab({GUI, id, revision, target, fields, render, container}) {
  if (!id || !revision || !Object.keys(fields).length) {
    throw new Error('Parameter identity and fields are required');
  }
  if (typeof render !== 'function' || typeof container?.append !== 'function') {
    throw new Error('Renderer and DOM container are required');
  }
  for (const field of Object.values(fields)) {
    if (!Number.isFinite(field.min) || !Number.isFinite(field.max) || field.min > field.max || !Number.isFinite(field.step) || field.step <= 0) {
      throw new Error('Numeric field ranges and positive steps are required');
    }
  }
  const baseline = {};
  const ui = {};
  const controls = [];
  let disposed = false;
  let lastImport = null;

  function validate(values) {
    if (!values || typeof values !== 'object' || Array.isArray(values)) {
      throw new Error('Settings must be an object');
    }
    for (const [key, value] of Object.entries(values)) {
      const field = Object.hasOwn(fields, key) && fields[key];
      const descriptor = Object.getOwnPropertyDescriptor(target, key);
      if (!field || !descriptor?.writable || !Number.isFinite(value) || value < field.min || value > field.max) {
        throw new Error(`Invalid numeric setting ${key}`);
      }
    }
  }

  for (const key of Object.keys(fields)) {
    baseline[key] = target[key];
    ui[key] = target[key];
  }
  validate(baseline);
  const gui = new GUI({title: '参数试验', container, width: 280});

  function sync() {
    for (const key of Object.keys(fields)) ui[key] = target[key];
    for (const control of controls) control.updateDisplay();
  }

  function snapshot() {
    return {schema: 1, id, revision, values: Object.fromEntries(Object.keys(fields).map(key => [key, target[key]]))};
  }

  function commit(preset) {
    if (disposed) throw new Error('Parameter lab is disposed');
    if (preset?.schema !== 1 || preset.id !== id || preset.revision !== revision) {
      throw new Error('Preset identity mismatch');
    }
    validate(preset.values);
    const previous = snapshot().values;
    Object.assign(target, preset.values);
    try {
      render();
    } catch (error) {
      Object.assign(target, previous);
      render();
      sync();
      throw error;
    }
    sync();
    return snapshot();
  }

  function apply(preset) {
    if (gui.domElement.contains(document.activeElement) && document.activeElement.tagName === 'INPUT') {
      throw new Error('Finish active parameter input before applying an external preset');
    }
    return commit(preset);
  }

  function restore() {
    return apply({schema: 1, id, revision, values: baseline});
  }

  const fileInput = document.createElement('input');
  fileInput.type = 'file';
  fileInput.accept = '.json,application/json';
  fileInput.hidden = true;
  fileInput.dataset.parameterPreset = id;
  container.append(fileInput);
  const listeners = new AbortController();
  fileInput.addEventListener('change', async () => {
    const file = fileInput.files[0];
    if (!file) return;
    try {
      apply(JSON.parse(await file.text()));
      lastImport = 'applied';
    } catch (error) {
      lastImport = error.message;
    }
    fileInput.value = '';
  }, {signal: listeners.signal});

  function save() {
    const url = URL.createObjectURL(new Blob([JSON.stringify(snapshot(), null, 2) + '\n'], {type: 'application/json'}));
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `${id}-settings.json`;
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  for (const [key, field] of Object.entries(fields)) {
    const control = gui.add(ui, key, field.min, field.max, field.step).name(field.label);
    control.domElement.dataset.parameter = key;
    control.onChange(value => {
      try {
        commit({schema: 1, id, revision, values: {[key]: value}});
      } catch (error) {
        sync();
        lastImport = error.message;
      }
    });
    controls.push(control);
  }
  const actions = {save, load: () => fileInput.click(), restore};
  gui.add(actions, 'save').name('导出参数');
  gui.add(actions, 'load').name('导入参数');
  gui.add(actions, 'restore').name('恢复调参基线');
  sync();

  return {
    apply, snapshot, restore,
    get lastImport() { return lastImport; },
    dispose() {
      if (disposed) return;
      commit({schema: 1, id, revision, values: baseline});
      disposed = true;
      listeners.abort();
      fileInput.remove();
      gui.destroy();
    },
  };
}
