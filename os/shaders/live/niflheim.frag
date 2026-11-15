// Niflheim: ranges of ice under a low winter sun, snow on their sunward faces, mist drifting between them, snow falling.
vec3 paint(vec2 p, float t) {
    float e = px();
    vec3 col = mix(tintB.rgb * 1.3 + glowA.rgb * 0.12, tintA.rgb * 0.72, ss(0.15, 1.0, p.y));
    vec2 sun = vec2(-0.45, 0.6);
    float sd = length(p - sun);
    col += glowB.rgb * (0.26 * exp(-sd * 9.0) + 0.08 * exp(-sd * 2.5));
    col = mix(col, mix(tintA.rgb, vec3(0.96), 0.55), day * 0.6);
    for (int i = 0; i < 3; i++) {
        float fi = float(i);
        float base = 0.36 - fi * 0.11;
        float amp = 0.17 + fi * 0.04;
        float x = p.x * (1.0 + fi * 0.45) + fi * 9.1;
        float hgt = base + ridge(x, 0.9) * amp;
        float m = ss(hgt + e * 1.5, hgt - e * 1.5, p.y);
        float below = hgt - p.y;
        // light from the sun's side, varying slowly along the range (no hard edges), snow thickest near the crests,
        // broken by gullies that run down the slopes
        float face = ridgeN(x + 0.16, 0.9, 2) - ridgeN(x - 0.16, 0.9, 2);
        float lit = ss(-0.25, 0.25, face);
        float gully = fbm(vec2(x * 6.0 + below * 14.0 * (lit - 0.5), below * 18.0 + fi * 3.0));
        float snow = ss(0.55, 0.15, below * (5.0 + fi * 2.0) + gully * 0.45);
        vec3 rock = mix(tintB.rgb * (0.5 - fi * 0.14), tintA.rgb * 0.35, 0.3);
        vec3 shade = mix(tintB.rgb, glowA.rgb, 0.28) * (0.62 - fi * 0.16);
        vec3 sunlit = mix(glowB.rgb, vec3(0.92, 0.96, 1.0), 0.45) * (0.8 - fi * 0.15);
        vec3 c = mix(rock, mix(shade, sunlit, lit), snow);
        c *= 0.9 + 0.2 * noise(vec2(x * 30.0, p.y * 60.0));                          // a little grain in the rock and snow
        c = mix(c, col, 0.38 - fi * 0.13);                                           // distance takes on the sky's colour
        c = mix(c, mix(tintB.rgb, vec3(0.92), 0.5), day * 0.35);
        col = mix(col, c, m);
        float mist = fbm(vec2(p.x * 1.6 + t * (0.010 + fi * 0.006), p.y * 7.0 + fi * 4.0));
        float band = ss(base + 0.11, base - 0.02, p.y) * ss(base - 0.13, base, p.y);
        col = mix(col, mix(tintB.rgb * 1.45, glowB.rgb, 0.25) + day * 0.2, band * ss(0.35, 0.78, mist) * 0.5);
    }
    for (int i = 0; i < 3; i++) {
        float fi = float(i);
        float sc = 18.0 - fi * 5.0;
        vec2 q = p * sc;
        q.y += t * (0.05 + fi * 0.045) * sc * 0.3;
        q.x += sin(t * 0.25 + q.y * 0.45 + fi * 2.0) * 0.35 + t * 0.03 * sc * 0.1;
        vec2 id = floor(q); vec2 f = fract(q) - 0.5;
        float h = hash12(id + fi * 31.0);
        vec2 o = (hash22(id + fi * 5.0) - 0.5) * 0.6;
        float size = 0.025 + 0.02 * hash12(id + 2.2) + fi * 0.012;
        float flake = step(0.84, h) * ss(size, size * 0.2, length((f - o) * vec2(1.0, 0.65)));
        col += vec3(0.92, 0.96, 1.0) * flake * (0.22 + fi * 0.2) * (1.0 - day * 0.5);
    }
    return col;
}
