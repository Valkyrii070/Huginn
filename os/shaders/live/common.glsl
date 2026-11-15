// Huginn OS live wallpapers: what every realm's scene shares. A scene file adds `vec3 paint(vec2 p, float t)`;
// scripts/make-live-wallpapers.py puts this, the scene and main() together and compiles them with qsb.
#version 440
layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;
layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    float time;      // seconds of motion: it slows down and stops, it never jumps
    float day;       // 0 at night (the sign-in screen, the dark appearance) … 1 by day (the light appearance)
    vec2 res;        // the size, in pixels
    vec4 tintA;      // the realm's two tints
    vec4 tintB;
    vec4 glowA;      // and its glow pair
    vec4 glowB;
};

// smoothstep, defined for edges either way round (GLSL leaves smoothstep(a, b, x) with a > b undefined)
float ss(float a, float b, float x) { float t = clamp((x - a) / (b - a), 0.0, 1.0); return t * t * (3.0 - 2.0 * t); }
float hash11(float p) { p = fract(p * 0.1031); p *= p + 33.33; p *= p + p; return fract(p); }
float hash12(vec2 p) { vec3 p3 = fract(vec3(p.xyx) * 0.1031); p3 += dot(p3, p3.yzx + 33.33); return fract((p3.x + p3.y) * p3.z); }
vec2 hash22(vec2 p) { vec3 p3 = fract(vec3(p.xyx) * vec3(0.1031, 0.1030, 0.0973)); p3 += dot(p3, p3.yzx + 33.33); return fract((p3.xx + p3.yz) * p3.zy); }
float noise1(float x) { float i = floor(x); float f = fract(x); return mix(hash11(i), hash11(i + 1.0), f * f * (3.0 - 2.0 * f)); }
float noise(vec2 p) {
    vec2 i = floor(p); vec2 f = fract(p); vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(mix(hash12(i), hash12(i + vec2(1.0, 0.0)), u.x), mix(hash12(i + vec2(0.0, 1.0)), hash12(i + vec2(1.0, 1.0)), u.x), u.y);
}
float fbm1(float x) { float v = 0.0; float a = 0.5; for (int i = 0; i < 5; i++) { v += a * noise1(x); x = x * 2.03 + 17.0; a *= 0.5; } return v; }
float fbm(vec2 p) { float v = 0.0; float a = 0.5; for (int i = 0; i < 5; i++) { v += a * noise(p); p = mat2(1.6, 1.2, -1.2, 1.6) * p + 3.1; a *= 0.5; } return v; }
// A skyline: soft hills (sharp 0) to steep peaks (sharp 1), about 0…1 high. `octaves` 5 for the outline, fewer
// for a smoother version of the same line (the lit and shaded faces of a range).
float ridgeN(float x, float sharp, int octaves) {
    float v = 0.0; float a = 0.5;
    for (int i = 0; i < 5; i++) {
        if (i >= octaves) break;
        float n = noise1(x); v += a * mix(n, 1.0 - abs(n * 2.0 - 1.0), sharp); x = x * 2.1 + 5.3; a *= 0.5;
    }
    return (v - 0.47) * 1.8 + 0.5;
}
float ridge(float x, float sharp) { return ridgeN(x, sharp, 5); }
// Stars: one in `density` of a grid's cells, each its own size, twinkling at its own pace.
float stars(vec2 p, float t, float density) {
    vec2 g = p * 70.0; vec2 id = floor(g); vec2 f = fract(g) - 0.5;
    float h = hash12(id);
    vec2 o = (hash22(id) - 0.5) * 0.7;
    float size = mix(0.04, 0.10, hash12(id + 4.7));
    float d = length(f - o);
    float tw = 0.65 + 0.35 * sin(t * (0.7 + 2.0 * hash12(id + 2.3)) + h * 50.0);
    return step(1.0 - density, h) * (ss(size, size * 0.15, d) + 0.18 * ss(size * 3.5, 0.0, d)) * tw * mix(0.35, 1.0, hash12(id + 9.9));
}
float px() { return 1.0 / max(res.y, 1.0); }
