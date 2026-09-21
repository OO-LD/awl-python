# Explainer

The explainer video, a frame per beat. It is silent and carries its script on
screen, so these stills are the whole of it: nobody reviews a video in a pull
request, they look at frames.

Everything shown as AWL-LD output is real output from this repository, produced
by the pipeline rather than mocked up.

<div class="awl-shot" tabindex="0">
<div class="awl-shot__stage">
<img class="awl-shot__slide" src="" alt="">
</div>
<div class="awl-shot__controls">
<button class="awl-shot__prev" type="button" aria-label="Previous beat">Previous</button>
<span class="awl-shot__scene"></span>
<span class="awl-shot__caption"></span>
<button class="awl-shot__next" type="button" aria-label="Next beat">Next</button>
</div>
<div class="awl-shot__fallback">
<img src="assets/explainer/01-question-file.png" alt="question file" loading="lazy">
<img src="assets/explainer/02-question-three.png" alt="question three" loading="lazy">
<img src="assets/explainer/03-question-punch.png" alt="question punch" loading="lazy">
<img src="assets/explainer/04-claim.png" alt="claim" loading="lazy">
<img src="assets/explainer/05-notation-document.png" alt="notation document" loading="lazy">
<img src="assets/explainer/06-notation-collapse.png" alt="notation collapse" loading="lazy">
<img src="assets/explainer/07-notation-rdf.png" alt="notation rdf" loading="lazy">
<img src="assets/explainer/08-layers-tree-alone.png" alt="layers tree alone" loading="lazy">
<img src="assets/explainer/09-layers-five.png" alt="layers five" loading="lazy">
<img src="assets/explainer/10-layers-one-node.png" alt="layers one node" loading="lazy">
<img src="assets/explainer/11-answers-comments.png" alt="answers comments" loading="lazy">
<img src="assets/explainer/12-answers-writes.png" alt="answers writes" loading="lazy">
<img src="assets/explainer/13-answers-computed.png" alt="answers computed" loading="lazy">
<img src="assets/explainer/14-editor-blocks.png" alt="editor blocks" loading="lazy">
<img src="assets/explainer/15-editor-trace.png" alt="editor trace" loading="lazy">
<img src="assets/explainer/16-editor-browser.png" alt="editor browser" loading="lazy">
<img src="assets/explainer/17-end-card.png" alt="end card" loading="lazy">
</div>
</div>

Left and right step through the beats. The frame numbers come from
`media/explainer/scripts/stills.mjs`, so retiming a scene moves these with it;
rebuild them with `npm run stills` in that directory.
