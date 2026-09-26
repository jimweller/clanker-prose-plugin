'use strict';

// Port of tools/render-template.py. Substitution runs against the template only,
// so a reply containing a literal {{catalog}} cannot inject the contract.
function render(template, values) {
  const missing = Object.keys(values).filter((k) => !template.includes(`{{${k}}}`));
  if (missing.length > 0) throw new Error(`template has no placeholder for ${missing.join(', ')}`);
  return template.replace(/\{\{(\w+)\}\}/g, (whole, name) => (Object.prototype.hasOwnProperty.call(values, name) ? values[name] : whole));
}

module.exports = { render };
