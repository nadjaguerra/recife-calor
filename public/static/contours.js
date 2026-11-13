'use strict';
const contourVertex = "attribute vec2 aPos;\nvoid main() { gl_Position = vec4(aPos, 0.0, 1.0); }";
const contourFragment = "#extension GL_OES_standard_derivatives : enable\n\nprecision mediump float;\nuniform vec2 uSize;\nuniform float uTime;\nuniform float uLevels;\nuniform float uWidth;\nuniform vec3 uInk;\nuniform vec3 uPaper;\n\nfloat hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }\n\nfloat noise(vec2 p) {\n  vec2 i = floor(p);\n  vec2 f = fract(p);\n  f = f * f * (3.0 - 2.0 * f);\n  return mix(\n    mix(hash(i), hash(i + vec2(1.0, 0.0)), f.x),\n    mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), f.x),\n    f.y);\n}\n\n// Three octaves; the landscape morphs by sliding each octave a different way.\nfloat landscape(vec2 p, float t) {\n  float v = 0.0;\n  v += 0.55 * noise(p * 1.4 + vec2(t * 0.05, -t * 0.03));\n  v += 0.30 * noise(p * 3.1 + vec2(-t * 0.04, t * 0.06) + 7.0);\n  v += 0.15 * noise(p * 6.5 + vec2(t * 0.08, t * 0.02) + 19.0);\n  return v;\n}\n\nvoid main() {\n  vec2 uv = gl_FragCoord.xy / uSize;\n  vec2 p = vec2(uv.x * uSize.x / uSize.y, uv.y);\n  float h = landscape(p, uTime) * uLevels;\n  // Distance to the nearest whole level, in levels. The field's gradient\n  // converts a pixel width into level units, so lines stay the same width on\n  // steep slopes and on flats.\n  float grad = length(vec2(dFdx(h), dFdy(h))) + 1e-5;\n  float f = fract(h);\n  float d = min(f, 1.0 - f);\n  // (\"half\" is reserved in GLSL ES, hence the longer name.)\n  float halfWidth = uWidth * grad;\n  float aa = grad;\n  float line = 1.0 - smoothstep(halfWidth, halfWidth + aa, d);\n  float thick = 1.0 - smoothstep(halfWidth * 2.2, halfWidth * 2.2 + aa, d);\n  // Every fifth contour is an index line: thicker and fully opaque.\n  float level = floor(h + 0.5);\n  float isIndex = 1.0 - step(0.2, fract(level / 5.0));\n  float ink = max(line * 0.55, thick * isIndex);\n  gl_FragColor = vec4(mix(uPaper, uInk, ink), 1.0);\n}\n";

(() => {
  const canvas = document.querySelector('.intro-contours');
  if (!canvas) return;
  const gl = canvas.getContext('webgl', { antialias: false });
  if (!gl?.getExtension('OES_standard_derivatives')) return;

  const program = gl.createProgram();
  for (const [type, source] of [[gl.VERTEX_SHADER, contourVertex], [gl.FRAGMENT_SHADER, contourFragment]]) {
    const shader = gl.createShader(type);
    gl.shaderSource(shader, source);
    gl.compileShader(shader);
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) return;
    gl.attachShader(program, shader);
    gl.deleteShader(shader);
  }
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) return;
  gl.useProgram(program);
  const buffer = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
  const position = gl.getAttribLocation(program, 'aPos');
  gl.enableVertexAttribArray(position);
  gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 0, 0);
  const uniform = name => gl.getUniformLocation(program, name);
  gl.uniform3f(uniform('uInk'), 0.86, 0.54, 0.37);
  gl.uniform3f(uniform('uPaper'), 0.44, 0.18, 0.13);
  gl.uniform1f(uniform('uLevels'), 17);
  gl.uniform1f(uniform('uWidth'), 0.48);
  const time = uniform('uTime');
  const size = uniform('uSize');
  const motion = matchMedia('(prefers-reduced-motion: reduce)');
  let elapsed = 0, previous = 0, frame = 0, visible = false;
  function draw() {
    gl.uniform1f(time, elapsed);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
  }
  function tick(now) {
    elapsed += Math.min((now - previous) / 1000, 0.1) * 0.65;
    previous = now;
    draw();
    frame = requestAnimationFrame(tick);
  }
  function sync() {
    cancelAnimationFrame(frame);
    if (visible && !document.hidden && !motion.matches) {
      previous = performance.now();
      frame = requestAnimationFrame(tick);
    }
  }
  canvas.hidden = false;
  const resize = new ResizeObserver(() => {
    canvas.width = Math.max(1, canvas.clientWidth);
    canvas.height = Math.max(1, canvas.clientHeight);
    gl.viewport(0, 0, canvas.width, canvas.height);
    gl.uniform2f(size, canvas.width, canvas.height);
    draw();
  });
  resize.observe(canvas);
  const intersection = new IntersectionObserver(([entry]) => {
    visible = entry.isIntersecting;
    sync();
  });
  intersection.observe(canvas);
  motion.addEventListener('change', sync);
  document.addEventListener('visibilitychange', sync);
})();
