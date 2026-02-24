/**
 * AI Transcriptor — 3D Wave & Particle Background
 * Beautiful animated water-wave effect with sparkling particles
 * by Shivam Kole
 */

(function () {
    'use strict';

    const canvas = document.createElement('canvas');
    canvas.id = 'bgCanvas';
    canvas.style.cssText = `
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        z-index: 0;
        pointer-events: none;
    `;
    document.body.prepend(canvas);

    const ctx = canvas.getContext('2d');
    let width, height, dpr;
    let animationId;
    let time = 0;

    // ─── Particles (sparkles) ───────────────────────────────────
    const particles = [];
    const PARTICLE_COUNT = 80;

    class Particle {
        constructor() {
            this.reset();
        }

        reset() {
            this.x = Math.random() * width;
            this.y = Math.random() * height;
            this.size = Math.random() * 2.5 + 0.5;
            this.speedX = (Math.random() - 0.5) * 0.3;
            this.speedY = (Math.random() - 0.5) * 0.2 - 0.1;
            this.opacity = Math.random() * 0.6 + 0.1;
            this.opacityDir = Math.random() * 0.008 + 0.002;
            this.hue = 210 + Math.random() * 40; // Blue-purple range
            this.twinkleSpeed = Math.random() * 0.02 + 0.01;
            this.twinkleOffset = Math.random() * Math.PI * 2;
        }

        update() {
            this.x += this.speedX;
            this.y += this.speedY;

            // Twinkle
            this.opacity = 0.15 + Math.abs(Math.sin(time * this.twinkleSpeed + this.twinkleOffset)) * 0.55;

            // Wrap around
            if (this.x < -10) this.x = width + 10;
            if (this.x > width + 10) this.x = -10;
            if (this.y < -10) this.y = height + 10;
            if (this.y > height + 10) this.y = -10;
        }

        draw() {
            ctx.beginPath();
            ctx.arc(this.x, this.y, this.size, 0, Math.PI * 2);
            ctx.fillStyle = `hsla(${this.hue}, 80%, 75%, ${this.opacity})`;
            ctx.fill();

            // Glow effect
            if (this.size > 1.5) {
                ctx.beginPath();
                ctx.arc(this.x, this.y, this.size * 3, 0, Math.PI * 2);
                ctx.fillStyle = `hsla(${this.hue}, 80%, 75%, ${this.opacity * 0.15})`;
                ctx.fill();
            }
        }
    }

    // ─── Wave Configuration ─────────────────────────────────────
    const waves = [
        { amplitude: 25, frequency: 0.008, speed: 0.015, yOffset: 0.75, color: [59, 130, 246], opacity: 0.06 },
        { amplitude: 20, frequency: 0.012, speed: 0.02, yOffset: 0.78, color: [99, 102, 241], opacity: 0.05 },
        { amplitude: 30, frequency: 0.006, speed: 0.01, yOffset: 0.82, color: [139, 92, 246], opacity: 0.04 },
        { amplitude: 15, frequency: 0.015, speed: 0.025, yOffset: 0.7, color: [59, 130, 246], opacity: 0.03 },
        { amplitude: 18, frequency: 0.01, speed: 0.018, yOffset: 0.65, color: [6, 182, 212], opacity: 0.025 },
    ];

    // ─── Mesh Grid (3D depth illusion) ──────────────────────────
    function drawMeshWave(wave, t) {
        const baseY = height * wave.yOffset;

        ctx.beginPath();
        ctx.moveTo(0, height);

        for (let x = 0; x <= width; x += 2) {
            const y = baseY +
                Math.sin(x * wave.frequency + t * wave.speed) * wave.amplitude +
                Math.sin(x * wave.frequency * 1.5 + t * wave.speed * 0.7) * wave.amplitude * 0.4 +
                Math.cos(x * wave.frequency * 0.5 + t * wave.speed * 1.3) * wave.amplitude * 0.3;

            ctx.lineTo(x, y);
        }

        ctx.lineTo(width, height);
        ctx.closePath();

        // Gradient fill
        const gradient = ctx.createLinearGradient(0, baseY - wave.amplitude, 0, height);
        gradient.addColorStop(0, `rgba(${wave.color.join(',')}, ${wave.opacity})`);
        gradient.addColorStop(0.5, `rgba(${wave.color.join(',')}, ${wave.opacity * 0.5})`);
        gradient.addColorStop(1, `rgba(${wave.color.join(',')}, 0)`);
        ctx.fillStyle = gradient;
        ctx.fill();
    }

    // ─── Horizontal light streaks ───────────────────────────────
    function drawLightStreaks(t) {
        const streaks = [
            { y: height * 0.2, width: 400, speed: 0.0003, opacity: 0.03 },
            { y: height * 0.4, width: 300, speed: 0.0005, opacity: 0.025 },
            { y: height * 0.6, width: 350, speed: 0.0004, opacity: 0.02 },
        ];

        streaks.forEach(s => {
            const x = ((t * s.speed * width) % (width + s.width * 2)) - s.width;
            const gradient = ctx.createLinearGradient(x, 0, x + s.width, 0);
            gradient.addColorStop(0, `rgba(59, 130, 246, 0)`);
            gradient.addColorStop(0.5, `rgba(59, 130, 246, ${s.opacity})`);
            gradient.addColorStop(1, `rgba(99, 102, 241, 0)`);
            ctx.fillStyle = gradient;
            ctx.fillRect(x, s.y - 1, s.width, 2);
        });
    }

    // ─── Connection Lines between nearby particles ──────────────
    function drawConnections() {
        const maxDist = 120;
        for (let i = 0; i < particles.length; i++) {
            for (let j = i + 1; j < particles.length; j++) {
                const dx = particles[i].x - particles[j].x;
                const dy = particles[i].y - particles[j].y;
                const dist = Math.sqrt(dx * dx + dy * dy);
                if (dist < maxDist) {
                    const opacity = (1 - dist / maxDist) * 0.08;
                    ctx.beginPath();
                    ctx.moveTo(particles[i].x, particles[i].y);
                    ctx.lineTo(particles[j].x, particles[j].y);
                    ctx.strokeStyle = `rgba(100, 140, 255, ${opacity})`;
                    ctx.lineWidth = 0.5;
                    ctx.stroke();
                }
            }
        }
    }

    // ─── Main Render Loop ───────────────────────────────────────
    function render() {
        time++;
        ctx.clearRect(0, 0, width, height);

        // Draw light streaks
        drawLightStreaks(time);

        // Draw waves (back to front)
        for (let i = waves.length - 1; i >= 0; i--) {
            drawMeshWave(waves[i], time);
        }

        // Draw connection lines
        drawConnections();

        // Update and draw particles
        particles.forEach(p => {
            p.update();
            p.draw();
        });

        animationId = requestAnimationFrame(render);
    }

    // ─── Resize Handler ─────────────────────────────────────────
    function resize() {
        dpr = Math.min(window.devicePixelRatio || 1, 2);
        width = window.innerWidth;
        height = window.innerHeight;
        canvas.width = width * dpr;
        canvas.height = height * dpr;
        canvas.style.width = width + 'px';
        canvas.style.height = height + 'px';
        ctx.scale(dpr, dpr);

        // Re-init particles on resize
        particles.length = 0;
        for (let i = 0; i < PARTICLE_COUNT; i++) {
            particles.push(new Particle());
        }
    }

    // ─── Init ───────────────────────────────────────────────────
    window.addEventListener('resize', resize);
    resize();
    render();

    // Cleanup on page unload
    window.addEventListener('beforeunload', () => {
        cancelAnimationFrame(animationId);
    });
})();
