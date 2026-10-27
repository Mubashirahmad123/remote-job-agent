/**
 * GESTURES.JS — swipe-to-dismiss with velocity handoff.
 *
 * The sheets in this app (the job detail sheet, the nav drawer) currently move
 * on a fixed timeline: they play a transition nobody can influence. The thing
 * that makes a surface feel alive is that it can be *grabbed* — it follows
 * the finger, it inherits the velocity of the release, and it can be caught
 * and reversed at any instant.
 *
 * The rules this implements, and why each one is there:
 *
 *   1:1 tracking     The surface follows the finger exactly. It never snaps
 *                    to a centre or animates to a target while the finger is
 *                    still down.
 *   hysteresis       A 10px threshold before the gesture commits, so a tap
 *                    that jitters is not a drag.
 *   axis lock        Once the gesture is clearly on one axis, the other axis
 *                    is released. A vertical drag must never fight the
 *                    content's own scrolling.
 *   rubber-banding   Past the boundary the surface resists progressively
 *                    instead of stopping dead. A hard stop reads as "frozen";
 *                    continuous resistance reads as "there is nothing more
 *                    here".
 *   projection       The release velocity decides the outcome, not the
 *                    release position. A flick throws the surface even if it
 *                    barely moved — the same way a scroll throws.
 *   velocity handoff The exit is timed from the release velocity, so the
 *                    motion continues instead of stopping and restarting.
 *
 * A real handoff needs a spring that blends velocity through a re-target.
 * There is no spring library in this project (no build step, no dependencies),
 * so the handoff is approximated by deriving the exit duration from the
 * release velocity — the honest CSS equivalent, and the part a user can feel.
 *
 * ONE THING THE CALLER MUST DO: give the surface a `touch-action`.
 *
 * A browser decides to scroll on the compositor, and the moment it does it
 * cancels the pointer events — a 1:1 drag would die after a single frame.
 * `preventDefault()` on `touchmove` cannot beat that (measured here: the
 * cancel still arrives, one millisecond after the touch). The only reliable
 * way to own a touch drag is `touch-action`, which the browser latches when
 * the gesture starts:
 *
 *   - a surface dragged on the X axis wants `touch-action: pan-y` — the
 *     browser keeps vertical panning (so the content still scrolls) and the
 *     horizontal gesture belongs to the app;
 *   - a surface dragged on the Y axis wants `touch-action: none` on the
 *     region that starts the drag, because there the browser must not claim
 *     the vertical pan at all. A sheet that also has to scroll its content
 *     therefore needs a drag handle (the grabber), which is also the
 *     affordance that tells the user the sheet can be moved.
 */

window.JobAgent = window.JobAgent || {};

JobAgent.gestures = {
  /**
   * Apple's projection function: where a flick is *going*, not where it
   * stopped. `decelerationRate` is the same 0.998 normal scrolling uses.
   */
  project(velocity /* px/s */, decelerationRate = 0.998) {
    return (velocity / 1000) * decelerationRate / (1 - decelerationRate);
  },

  /**
   * Progressive resistance past a boundary. The further past it the surface
   * is dragged, the less it follows — real things slow down before they stop.
   */
  rubberband(overshoot, dimension, constant = 0.55) {
    return (overshoot * dimension * constant) / (dimension + constant * Math.abs(overshoot));
  },

  /**
   * Attach a swipe-to-dismiss gesture.
   *
   * @param {HTMLElement} el        the surface
   * @param {object}      options
   * @param {'x'|'y'}     options.axis      the drag axis
   * @param {number}      options.direction +1 dismisses toward +axis, -1 toward -axis
   * @param {Function}    options.onDismiss called when the gesture commits
   * @param {Function}    options.canStart  (delta) => boolean — veto a gesture
   * @param {Function}    options.onProgress (ratio) => void — continuous feedback
   * @param {number}      options.dismissThreshold fraction of the surface to pass
   */
  swipeToDismiss(el, options = {}) {
    if (!el || typeof el.addEventListener !== 'function') return () => {};

    const {
      axis = 'y',
      direction = 1,
      onDismiss,
      canStart = () => true,
      onGrab,
      onProgress,
      handle,
      dismissThreshold = 0.35,
      easing = 'cubic-bezier(0.32, 0.72, 0, 1)',
    } = options;

    const horizontal = axis === 'x';
    const axisPos = (e) => (horizontal ? e.clientX : e.clientY);
    const crossPos = (e) => (horizontal ? e.clientY : e.clientX);

    let pointerId = null;
    let startPos = 0;
    let startCross = 0;
    let dragging = false;
    let offset = 0;      // in dismissal space: positive means "toward dismissal"
    let velocity = 0;    // px per millisecond
    let samples = [];

    const dimension = () => {
      const rect = el.getBoundingClientRect();
      const size = horizontal ? window.innerWidth : rect.height;
      return size || 1;
    };

    const applyTransform = (px) => {
      el.style.transform = horizontal ? `translateX(${px}px)` : `translateY(${px}px)`;
    };

    const endGesture = () => {
      pointerId = null;
      dragging = false;
      offset = 0;
      velocity = 0;
      samples = [];
    };

    const onPointerDown = (e) => {
      if (pointerId !== null) return;              // a second finger is ignored
      if (e.pointerType === 'mouse' && e.button !== 0) return;
      // A surface with a handle is only dragged by its handle: the browser
      // latches touch-action when the gesture starts, so the region the
      // finger lands on has to be the one that opted out of the browser's
      // scroll handling.
      if (handle && !handle.contains(e.target)) return;
      pointerId = e.pointerId;
      startPos = axisPos(e);
      startCross = crossPos(e);
      samples = [{ pos: startPos, time: e.timeStamp }];
      dragging = false;
      offset = 0;
    };

    const onPointerMove = (e) => {
      if (e.pointerId !== pointerId) return;
      const delta = axisPos(e) - startPos;
      const crossDelta = crossPos(e) - startCross;

      if (!dragging) {
        // Hysteresis: a tap that jitters is not a drag.
        if (Math.abs(delta) < 10) return;
        // Axis lock: the gesture belongs to whichever axis moved further.
        if (Math.abs(crossDelta) > Math.abs(delta)) return;
        if (!canStart(delta)) return;
        dragging = true;
        el.classList.add('is-dragging');
        armedClickSwallow = true;
        try { el.setPointerCapture(e.pointerId); } catch (_) { /* not capturable */ }
        // The surface was caught mid-flight: whatever it was doing, it now
        // belongs to the finger.
        if (onGrab) onGrab();
      }

      // Velocity from a short history, not just the last two events: a single
      // frame can be misleading at the end of a fast flick.
      samples.push({ pos: axisPos(e), time: e.timeStamp });
      if (samples.length > 6) samples.shift();
      const first = samples[0];
      const last = samples[samples.length - 1];
      const dt = last.time - first.time;
      velocity = dt > 0 ? (last.pos - first.pos) / dt : 0;

      // Work in dismissal space, where positive always means "toward
      // dismissal", so the sign rules stay readable for either axis.
      const signed = delta * direction;
      let value = signed;
      if (signed < 0) {
        // Past the boundary the surface resists rather than stopping dead.
        value = -JobAgent.gestures.rubberband(-signed, dimension());
      }
      offset = value;
      applyTransform(value * direction);

      if (onProgress) {
        const ratio = Math.max(0, Math.min(1, value / dimension()));
        onProgress(ratio);
      }
      // The surface is under the finger; the page must not scroll with it.
      if (e.cancelable) e.preventDefault();
    };

    const onPointerUp = (e) => {
      if (e.pointerId !== pointerId) return;
      const wasDragging = dragging;
      const dragOffset = offset;
      const dragVelocity = velocity;
      endGesture();
      if (!wasDragging) return;

      el.classList.remove('is-dragging');

      // Where the gesture was GOING. A flick throws the surface even if it
      // barely moved — the same way a scroll throws. The velocity is
      // expressed in dismissal space (like the offset), so a surface dragged
      // on the negative axis still projects forward, not backward.
      const signedVelocity = dragVelocity * direction;
      const projected = dragOffset + JobAgent.gestures.project(signedVelocity * 1000);
      const shouldDismiss = dragOffset > 0 && projected > dimension() * dismissThreshold;

      // The exit is timed from the release velocity: a fast flick leaves
      // quickly, a slow drag takes its time. This is the CSS stand-in for a
      // spring that carries velocity into the exit.
      const remaining = Math.abs(dimension() - dragOffset);
      const speed = Math.max(Math.abs(dragVelocity) * 1000, 1); // px/s
      const duration = Math.max(120, Math.min(340, Math.round((remaining / speed) * 1000)));

      el.style.transitionDuration = `${duration}ms`;
      el.style.transitionTimingFunction = easing;
      // Hand the surface back to CSS: the transition animates from the
      // position it was dragged to (the presentation value) to whichever
      // state the class implies. Starting from the target instead would
      // jump.
      el.style.transform = '';

      const restore = () => {
        el.style.transitionDuration = '';
        el.style.transitionTimingFunction = '';
      };
      setTimeout(restore, duration + 40);

      if (shouldDismiss && onDismiss) onDismiss();
    };

    const onPointerCancel = (e) => {
      if (e.pointerId !== pointerId) return;
      // The browser took the gesture (a scroll, a system gesture). Spring the
      // surface back rather than leaving it where it was.
      const wasDragging = dragging;
      endGesture();
      if (!wasDragging) return;
      el.classList.remove('is-dragging');
      el.style.transitionDuration = '220ms';
      el.style.transform = '';
      setTimeout(() => {
        el.style.transitionDuration = '';
      }, 280);
    };

    /**
     * A drag that committed must not also fire the click underneath it.
     */
    const swallowNextClick = (e) => {
      e.stopPropagation();
      e.preventDefault();
    };
    let armedClickSwallow = false;

    el.addEventListener('pointerdown', onPointerDown);
    el.addEventListener('pointermove', onPointerMove);
    el.addEventListener('pointerup', onPointerUp);
    el.addEventListener('pointercancel', onPointerCancel);
    el.addEventListener('click', (e) => {
      if (!armedClickSwallow) return;
      armedClickSwallow = false;
      swallowNextClick(e);
    }, true);

    return () => {
      el.removeEventListener('pointerdown', onPointerDown);
      el.removeEventListener('pointermove', onPointerMove);
      el.removeEventListener('pointerup', onPointerUp);
      el.removeEventListener('pointercancel', onPointerCancel);
    };
  }
};
