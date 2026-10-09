// WebGL globe (globe.gl, vendored). Same interface as the flat map: play(steps), destroy().

export function createGlobe(stage, geo) {
    const cs = getComputedStyle(document.documentElement);
    const css = (v) => cs.getPropertyValue(v).trim();
    const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
    const fills = new Map();
    const box = stage.getBoundingClientRect();
    stage.replaceChildren();
    const globe = window.Globe({ animateIn: !reduced })(stage)
        .width(box.width).height(box.height)
        .backgroundColor('rgba(0,0,0,0)')
        .showAtmosphere(true).atmosphereColor(css('--accent')).atmosphereAltitude(0.12)
        .polygonsData(geo.features)
        .polygonAltitude(0.006)
        .polygonCapColor((f) => fills.get(f.key) || (geo.langOf.has(f.key) ? css('--land-lang') : css('--land')))
        .polygonSideColor(() => 'rgba(0,0,0,0)')
        .polygonStrokeColor(() => css('--paper'))
        .polygonsTransitionDuration(reduced ? 0 : 400)
        .arcColor(() => css('--planetary'))
        .arcStroke(0.5)
        .arcDashLength(0.5).arcDashGap(0.15).arcDashAnimateTime(reduced ? 0 : 2200)
        .arcsTransitionDuration(0);
    const mat = globe.globeMaterial();
    mat.color?.set?.(css('--paper-2'));
    const controls = globe.controls();
    controls.autoRotate = !reduced;
    controls.autoRotateSpeed = 0.35;
    controls.enableZoom = false;
    const onResize = () => {
        const b = stage.getBoundingClientRect();
        globe.width(b.width).height(b.height);
    };
    addEventListener('resize', onResize);
    let timers = [];

    function play(steps, { animate }) {
        timers.forEach(clearTimeout);
        timers = [];
        fills.clear();
        const arcs = [];
        globe.arcsData([]);
        const lead = steps[0];
        if (lead?.anchor) globe.pointOfView({ lat: lead.anchor[1], lng: lead.anchor[0], altitude: 2.1 }, animate ? 1200 : 0);
        steps.forEach((s, i) => {
            const show = () => {
                for (const [key, colour] of s.countries) fills.set(key, colour);
                globe.polygonCapColor(globe.polygonCapColor());
                if (i > 0 && s.anchor && lead.anchor) {
                    arcs.push({ startLat: lead.anchor[1], startLng: lead.anchor[0], endLat: s.anchor[1], endLng: s.anchor[0] });
                    globe.arcsData([...arcs]);
                }
                s.onShow?.();
            };
            if (animate) timers.push(setTimeout(show, s.delay)); else show();
        });
    }

    return {
        play,
        destroy() {
            timers.forEach(clearTimeout);
            removeEventListener('resize', onResize);
            globe.pauseAnimation?.();
            globe._destructor?.();
            stage.replaceChildren();
        },
    };
}
