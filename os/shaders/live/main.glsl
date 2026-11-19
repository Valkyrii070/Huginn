void main() {
    vec2 uv = qt_TexCoord0;
    // scene space: y from 0 at the bottom to 1 at the top, x centred in the same units, so wide screens don't stretch it
    vec2 p = vec2((uv.x - 0.5) * res.x / max(res.y, 1.0), 1.0 - uv.y);
    vec3 c = paint(p, time);
    c *= mix(0.80, 1.0, ss(1.2, 0.35, length((uv - 0.5) * vec2(1.0, 1.25))));     // a soft vignette
    c += (hash12(gl_FragCoord.xy) + hash12(gl_FragCoord.xy * 1.37 + 9.1) - 1.0) / 255.0;  // dither: dark skies never band
    fragColor = vec4(clamp(c, 0.0, 1.0), 1.0) * qt_Opacity;
}
