// Bifröst: the bridge of light, an iridescent arc with sparks crossing it, rising out of a sea of cloud.
vec3 paint(vec2 p, float t) {
    vec3 col = mix(tintB.rgb * 1.15 + glowB.rgb * 0.08, tintA.rgb * 0.5, ss(0.0, 1.0, p.y));
    col += glowB.rgb * 0.10 * exp(-max(p.y - 0.1, 0.0) * 4.0);                       // a warm glow under it all
    col = mix(col, mix(tintA.rgb, vec3(0.93), 0.5), day * 0.6);
    col += stars(p, t, 0.03) * (1.0 - day) * ss(0.35, 0.8, p.y);
    vec2 q = p - vec2(0.55, -1.05);
    float r = length(q);
    float a = atan(q.y, q.x);
    float d = r - 1.72;
    float s = d / 0.085;                                                             // −1 … 1 across the bridge
    float flow = fbm(vec2(a * 9.0 - t * 0.05, s * 1.5 + t * 0.01));
    float band = exp(-s * s * 1.8);
    vec3 hue = mix(glowA.rgb, glowB.rgb, ss(-1.2, 1.2, s));
    hue += 0.10 * cos(6.2831 * (vec3(0.0, 0.33, 0.67) + s * 0.35 + a * 0.6 + t * 0.01));
    col += hue * band * (0.35 + 0.75 * flow) * mix(0.9, 0.55, day);
    col += mix(vec3(1.0), hue, 0.5) * exp(-s * s * 9.0) * 0.22 * (0.4 + flow);          // a bright core
    col += mix(glowA.rgb, glowB.rgb, 0.5) * exp(-abs(d) * 5.5) * 0.10;
    float s2 = (r - 1.72 - 0.22) / 0.05;
    col += mix(glowB.rgb, glowA.rgb, ss(-1.0, 1.0, s2)) * exp(-s2 * s2 * 2.0) * 0.12 * (0.5 + flow);
    vec2 g = vec2(a * 60.0 - t * 0.35, s * 2.2);
    vec2 id = floor(g); vec2 f = fract(g) - 0.5;
    float hh = hash12(id);
    vec2 o = (hash22(id + 3.0) - 0.5) * 0.6;
    float spark = step(0.86, hh) * ss(0.13, 0.0, length((f - o) * vec2(1.0, 2.2))) * (0.55 + 0.45 * sin(t * 1.6 + hh * 30.0));
    col += mix(vec3(1.0), glowB.rgb, 0.35) * spark * band;
    // two banks of cloud with crisp, lit tops; the nearer is darker
    for (int i = 0; i < 2; i++) {
        float fi = float(i);
        float x = p.x * (1.0 + fi * 0.5) + fi * 8.0 + t * (0.006 + fi * 0.005);
        float top = 0.30 - fi * 0.13 + (fbm1(x * 1.3) - 0.5) * 0.20 + (noise(vec2(x * 7.0, fi * 3.0)) - 0.5) * 0.035;
        float cm = ss(top + 0.006, top - 0.006, p.y);
        float inner = fbm(vec2(x * 3.0, p.y * 7.0 - t * 0.004));
        vec3 base = tintB.rgb * (0.62 - fi * 0.22) + glowB.rgb * 0.04;
        vec3 rim = tintB.rgb * 1.3 + glowB.rgb * (0.22 - fi * 0.08) + glowA.rgb * 0.06;
        vec3 cc = mix(base * (0.8 + 0.4 * inner), rim, exp(-max(top - p.y, 0.0) * (16.0 + fi * 8.0)));
        cc = mix(cc, mix(tintB.rgb, vec3(0.95), 0.55), day * 0.6);
        col = mix(col, cc, cm);
    }
    return col;
}
