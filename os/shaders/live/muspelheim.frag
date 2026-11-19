// Muspelheim: a plain of fire under rolling smoke, a volcano and its range dark against the glow, embers rising.
vec3 paint(vec2 p, float t) {
    float e = px();
    float hz = 0.28;                                                                 // the horizon
    vec2 crater = vec2(0.42, hz + 0.25);
    vec2 w = vec2(fbm(p * 1.4 + vec2(0.0, -t * 0.010)), fbm(p * 1.4 + vec2(5.2, 1.3) + t * 0.008));
    float smoke = fbm(p * vec2(1.5, 2.2) + w * 1.5 + vec2(t * 0.006, -t * 0.014));
    float lift = exp(-max(p.y - hz, 0.0) * 2.4);
    vec3 col = mix(tintA.rgb * 0.8, tintB.rgb * 0.45, ss(0.3, 1.0, p.y));
    col += glowA.rgb * 0.24 * lift * (0.5 + 0.9 * smoke) + glowB.rgb * 0.06 * lift * lift;
    col += glowA.rgb * 0.22 * exp(-length((p - crater) * vec2(2.2, 1.0)) * 4.0) * (0.6 + 0.6 * smoke);  // the plume, lit
    col = mix(col, col * 0.4, ss(0.42, 0.72, smoke) * ss(hz, hz + 0.45, p.y));            // darker billows
    // the volcano's plume, leaning with the wind, lit from below by the crater
    float rise = max(p.y - crater.y, 0.0);
    float plume = exp(-abs(p.x - crater.x - rise * 0.45 - sin(rise * 5.0 - t * 0.05) * 0.04) / (0.05 + rise * 0.45)) * ss(crater.y - 0.01, crater.y + 0.05, p.y);
    plume *= ss(0.3, 0.75, fbm(vec2(p.x * 3.0 - rise * 2.0, p.y * 4.0 - t * 0.035) + w));
    col = mix(col, mix(tintB.rgb * 0.3, glowA.rgb * 0.5 + glowB.rgb * 0.1, exp(-rise * 4.0)), plume * 0.75 * (1.0 - day * 0.5));
    col = mix(col, mix(tintA.rgb, vec3(0.95), 0.45), day * 0.55);
    // the range and the volcano, with a hot rim and a glowing crater
    float cone = hz + 0.25 - pow(abs(p.x - crater.x), 1.25) * 0.55;
    float far = max(hz + 0.01 + ridge(p.x * 1.1 + 2.0, 0.6) * 0.10, cone - (noise(vec2(p.x * 40.0, 1.0)) * 0.006));
    far = min(far, hz + 0.245);
    float fm = ss(far + e, far - e, p.y);
    col = mix(col, tintB.rgb * 0.30 + glowA.rgb * 0.05, fm);
    col += glowA.rgb * 0.30 * fm * exp(-max(far - p.y, 0.0) * 60.0);
    col += glowB.rgb * 0.9 * fm * exp(-length((p - crater) * vec2(1.0, 3.0)) * 45.0) * (0.8 + 0.2 * sin(t * 0.9));
    // the plain: rivers of fire seen in perspective, fading into heat haze at the horizon
    float pm = ss(hz + e, hz - e, p.y);
    float depth = 0.06 / max(hz - p.y, 0.003);
    float n = fbm(vec2(p.x * depth * 1.6, depth * 2.0) * 0.9 + vec2(t * 0.004, 0.0));
    float lava = pow(1.0 - abs(n * 2.0 - 1.0), 10.0);
    float throb = 0.75 + 0.25 * sin(t * 0.5 + n * 12.0);
    float nearer = ss(hz - 0.005, hz - 0.08, p.y);
    vec3 plain = tintB.rgb * 0.2 + mix(glowA.rgb, glowB.rgb, lava) * 1.25 * lava * throb * nearer;
    plain = mix(plain, glowA.rgb * 0.3 + tintB.rgb * 0.3, ss(hz - 0.06, hz, p.y) * 0.8);
    col = mix(col, mix(plain, mix(tintB.rgb, vec3(0.8), 0.35), day * 0.4), pm);
    for (int i = 0; i < 3; i++) {
        float fi = float(i);
        float sc = 9.0 + fi * 7.0;
        vec2 q = p * sc;
        q.y -= t * (0.25 + fi * 0.12) * sc * 0.05;
        q.x += sin(q.y * 0.35 + fi * 3.0 + t * 0.2) * 0.6;
        vec2 id = floor(q); vec2 f = fract(q) - 0.5;
        float h = hash12(id + fi * 17.0);
        vec2 o = (hash22(id + fi * 7.0) - 0.5) * 0.6;
        float d = length(f - o);
        float size = 0.05 + 0.04 * hash12(id + 1.7) - fi * 0.01;
        float flick = 0.5 + 0.5 * sin(t * (3.0 + h * 4.0) + h * 40.0);
        float glow = step(0.84, h) * (ss(size, 0.0, d) + 0.25 * ss(size * 4.0, 0.0, d)) * flick;
        col += mix(glowB.rgb, glowA.rgb, h) * glow * (1.0 - fi * 0.3) * ss(1.0, 0.25, p.y);
    }
    return col;
}
