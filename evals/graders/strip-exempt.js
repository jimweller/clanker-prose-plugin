// Removes the spans every prose rule exempts, so a grader never fires on a code
// fence, an inline code span, a URL, a clock time, or a ratio.
function stripExempt(text) {
  return text
    // The prose skill mandates [GAP: what is missing] for a fact the source
    // lacks, and that marker carries a colon by construction, so the colon
    // grader has to skip it or it punishes the behaviour the contract asks for.
    .replace(/\[\s*gaps?\s*:[^\]]*\]/gi, ' ')
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/`[^`\n]*`/g, ' ')
    .replace(/https?:\/\/\S+/g, ' ')
    .replace(/\b\d{1,2}:\d{2}(?::\d{2})?\b/g, ' ')
    .replace(/\b\d+:\d+\b/g, ' ');
}

module.exports = { stripExempt };
