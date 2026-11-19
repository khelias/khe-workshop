// Starts every stage on the page. Without WebGL the page keeps its text and photo.

function hasWebGL() {
  try {
    const context = document.createElement('canvas').getContext('webgl2');
    context?.getExtension('WEBGL_lose_context')?.loseContext();
    return Boolean(context);
  } catch {
    return false;
  }
}

const roots = document.querySelectorAll('[data-stage]');
if (roots.length && hasWebGL()) {
  try {
    const { startStage } = await import('./stage.js');
    roots.forEach((root) => startStage(root));
  } catch {
    roots.forEach((root) => {
      const status = root.querySelector('[data-stage-status]');
      status.textContent = JSON.parse(root.querySelector('[data-stage-config]').textContent).text.error;
      status.hidden = false;
    });
  }
} else {
  roots.forEach((root) => { root.dataset.nowebgl = 'true'; });
}
