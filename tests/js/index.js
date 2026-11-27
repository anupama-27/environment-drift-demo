"use strict";

// `node --test tests/js/` hands the directory to Node as one test file, and this is the file
// Node resolves it to. The suites live in the *.test.js files next to it.
require("./stats.test.js");
require("./scorers.test.js");
require("./schema.test.js");
require("./engine.test.js");
require("./paper.test.js");
require("./golden.test.js");
require("./format.test.js");
require("./compat.test.js");
