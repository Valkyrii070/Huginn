// Aurora: northern lights folding over a mountain range, under stars, mirrored in a still lake with mist on the far shore.
vec3 above(vec2 p, float t) {
    float e = px();
    vec3 col = mix(tintB.rgb * 1.2 + glowA.rgb * 0.045, mix(tintA.rgb, tintB.rgb, 0.5) * 0.9, ss(0.12, 0.55, p.y));
    col = mix(col, tintA.rgb * 0.45, ss(0.55, 1.05, p.y));
    col = mix(col, mix(tintA.rgb, vec3(0.92), 0.5), day * 0.6);
    col += stars(p, t, 0.035) * (1.0 - day) * ss(0.2, 0.55, p.y) * vec3(0.85, 0.92, 1.0);
    // three curtains, each folding, drifting and pulsing at its own pace
    vec3 au = vec3(0.0);
    for (int i = 0; i < 3; i++) {
        float fi = float(i);
        float x = p.x * (0.8 - fi * 0.17) + fi * 7.3;
        x += sin(p.y * 5.0 + x * 1.7 + t * 0.021 + fi) * 0.06;                     // the folds
        float edge = 0.56 + fi * 0.08 + (fbm1(x * 1.05 + t * (0.016 + fi * 0.005)) - 0.5) * 0.32 + sin(x * 1.8 + t * 0.028 + fi * 2.0) * 0.035;
        float h = p.y - edge;
        float rays = 0.40 + 0.60 * noise(vec2(x * 22.0 + t * 0.05, fi * 13.0 + t * 0.018));
        rays *= 0.55 + 0.45 * noise(vec2(x * 6.0 - t * 0.035, fi * 5.0));
        float lower = ss(-0.025, 0.006, h);
        float fade = exp(-max(h, 0.0) * (3.6 + fi * 2.2));
        float pulse = 0.4 + 0.6 * ss(0.2, 0.8, noise1(x * 0.55 - t * 0.022 + fi * 4.0));
        vec3 c = mix(glowA.rgb * 1.1, glowB.rgb, clamp(h * 2.4 + fi * 0.22, 0.0, 1.0));
        au += c * lower * fade * rays * pulse * (1.0 - fi * 0.27);
        au += glowA.rgb * 0.07 * exp(-abs(h) * 9.0) * pulse;                      // light spilling below each edge
    }
    col += au * mix(0.9, 0.45, day);
    // the far range, its crests caught by the light, reaching down to the shore
    float far = 0.20 + ridge(p.x * 1.05 + 3.0, 0.8) * 0.21;
    float fm = ss(far + e, far - e, p.y);
    vec3 farCol = mix(tintB.rgb * 0.5, col, 0.22) + glowA.rgb * 0.02;
    farCol *= mix(0.75, 1.0, ss(0.15, far, p.y));
    col = mix(col, mix(farCol, mix(tintB.rgb, vec3(0.85), 0.4), day * 0.5), fm);
    col += glowA.rgb * 0.16 * fm * exp(-max(far - p.y, 0.0) * 80.0) * (1.0 - day * 0.6);
    // mist along the far shore
    float mist = fbm(vec2(p.x * 1.8 + t * 0.011, p.y * 8.0 - t * 0.003));
    float band = ss(0.30, 0.17, p.y) * ss(0.13, 0.19, p.y);
    col = mix(col, mix(tintB.rgb * 1.4, glowA.rgb, 0.12) + day * 0.25, band * ss(0.3, 0.85, mist) * 0.45);
    return col;
}
vec3 paint(vec2 p, float t) {
    float water = 0.15;
    vec3 col;
    if (p.y >= water) {
        col = above(p, t);
    } else {
        // the lake: the sky upside down, broken into slow ripples, darker toward you
        float dy = water - p.y;
        float rip = (noise(vec2(p.x * 2.5 + t * 0.02, dy * 140.0 / (0.25 + dy * 6.0) - t * 0.25)) - 0.5) * (0.004 + dy * 0.06);
        col = above(vec2(p.x + rip, water + dy * 1.15), t) * 0.58;
        col = mix(col, tintB.rgb * 0.25, ss(0.0, 0.15, dy) * 0.45);
        col += glowA.rgb * 0.05 * exp(-dy * 260.0);                                  // the shoreline glints
        col = mix(col, mix(tintB.rgb, vec3(0.88), 0.45), day * 0.3);
    }
    // dark hills at both sides in front of the lake, opening in the middle
    float e = px();
    float open = ss(0.15, 0.85, abs(p.x + 0.08));
    float near = 0.05 + ridge(p.x * 2.2 + 11.0, 0.3) * 0.15 * open + open * 0.05;
    float nm = ss(near + e, near - e, p.y);
    col = mix(col, mix(tintB.rgb * 0.22, tintB.rgb * 0.7, day), nm);
    col += glowA.rgb * 0.05 * nm * exp(-max(near - p.y, 0.0) * 110.0);
    return col;
}
