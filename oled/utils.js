
// utils.js

function runButtonsLedsScript() {
    console.log("Running buttonsleds.js script...");
    // If buttonsleds.js doesn't require any arguments and can be run as a separate process
    runScript('buttonsleds');
}

function runRotaryScript(OLED) {
    console.log("Running rotary.js script...");
    // Instead of running as a separate process, require and invoke the module
    const rotary = require('./rotary');
    rotary(OLED); // Pass the OLED instance to the rotary module
}

function runScript(scriptName) {
    const { exec } = require('child_process');
    console.log(`Executing ${scriptName}.js...`);
    exec(`node ${scriptName}.js`, (error, stdout, stderr) => {
        if (error) {
            console.error(`Error executing ${scriptName}.js: ${error.message}`);
            return;
        }
        console.log(`${scriptName}.js output: ${stdout}`);
        if (stderr) console.error(`${scriptName}.js stderr: ${stderr}`);
    });
    console.log(`Finished executing ${scriptName}.js`);
}

module.exports = { runScript, runButtonsLedsScript, runRotaryScript };
