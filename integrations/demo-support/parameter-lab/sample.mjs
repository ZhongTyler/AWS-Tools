import GUI from './vendor/lil-gui.esm.js';
import {createParameterLab} from './parameter-lab.mjs';

const settings = {radius: 26, opacity: 0.75, trail: 4};
const state = {frame: 0, x: 80};
const canvas = document.querySelector('canvas');
const context = canvas.getContext('2d');
const fields = {
  radius: {label: '标记半径（px）', min: 8, max: 60, step: 1},
  opacity: {label: '标记透明度', min: 0.1, max: 1, step: 0.05},
  trail: {label: '轨迹长度', min: 0, max: 8, step: 1},
};
let rejectRenderOnce = false;
function render() {
  if (rejectRenderOnce) {
    rejectRenderOnce = false;
    throw new Error('Controlled renderer failure');
  }
  context.clearRect(0, 0, canvas.width, canvas.height);
  for (let index = settings.trail; index >= 0; index--) {
    context.beginPath();
    context.arc(state.x - index * 10, 140, settings.radius, 0, Math.PI * 2);
    context.fillStyle = `rgba(111, 224, 185, ${settings.opacity / (index + 1)})`;
    context.fill();
  }
  document.querySelector('#state').textContent = JSON.stringify({settings, state}, null, 2);
}
function step() { state.frame++; state.x = 80 + (state.frame * 24) % 400; render(); }
function restart() { state.frame = 0; state.x = 80; render(); }
const lab = createParameterLab({
  GUI, id: 'demo-parameter-sample', revision: 'numeric-view-v1',
  target: settings, fields, render, container: document.querySelector('#lab'),
});
document.querySelector('#step').addEventListener('click', step);
document.querySelector('#restart').addEventListener('click', restart);
window.demo = {
  lab, settings, step, restart,
  state: () => ({...state}),
  pixel: () => Array.from(context.getImageData(state.x, 140, 1, 1).data),
  failNextRender() { rejectRenderOnce = true; },
  directApply(values) { Object.assign(settings, values); render(); },
};
render();
