# Code
Huginn's code editor: your project's files, tabs, Git, a terminal and the language tools VS Code uses.

## Open a project
Press Open Folder… (Ctrl+O) and pick the folder. Code remembers which files you had open and opens them again next time. Recent projects are on the start page.

## Get anywhere fast
Ctrl+P finds a file as you type part of its name. Start with > for every command, : for a line number, or @ for a function or class in this file. Ctrl+Shift+P goes straight to the commands.

## Editing helpers
Enter keeps the indent (and adds one after a colon or an opening bracket). Brackets and quotes close themselves. Tab and Shift+Tab indent and outdent the lines you've selected. Ctrl+/ comments lines out and back in. Ctrl+= and Ctrl+- change the letter size; Alt+Z wraps long lines.

## Find and replace
Ctrl+F finds in this file, Ctrl+H replaces. Ctrl+Shift+F searches the whole project, and can replace everywhere it found. Aa matches case, W whole words, .* a pattern.

## Completions, problems and definitions
For Python, Code speaks to a language server: suggestions appear as you type (Ctrl+Space asks for them), mistakes are underlined and listed under Problems, Ctrl+I shows what something is, and F12 or Ctrl+click goes to where it's defined. Other languages work the same way once their server is installed (clangd for C and C++, rust-analyzer, gopls, typescript-language-server). Without one, Code still suggests words from the file and checks Python and JSON.

## Git
The branch icon on the left shows what changed. Click a file to see its changes, stage it with +, or throw the changes away. Write what changed and press Commit (if nothing is staged, everything is). The arrows pull and push. If the server wants a password, run the same command in the terminal once.

## Rename and find every use
F2 renames the thing under the cursor everywhere it's used, across the project (the language server knows where; open files change but aren't saved until you save them). Shift+F12 lists every place it's used in the Search panel. Without a language server, rename changes whole words in the file and the list is found by name.

## Run and the terminal
Ctrl+` opens a terminal under the code, in the project's folder. Run (Ctrl+F5) saves everything and runs the project its usual way (make, cargo run, npm run dev, go run…) or the file in front. Set the Run command… keeps your own in a file called .huginn-run.

## Debugging
Click beside a line number (or press F9) to put a red breakpoint there, then press F5. The program runs until it reaches one and stops; that line is marked, and the Debug panel shows the call stack, what every variable holds (open lists and objects a level at a time) and a console where you can work out an expression in the stopped program. F5 carries on, F10 steps over a line, F11 steps into a function, Shift+F11 steps out, Shift+F5 stops. Breakpoints stay with the project and move with their lines as you edit.
Python is debugged with debugpy. C, C++, Rust and Go use GDB on the program you built (build it with debugging information, such as gcc -g or cargo build): Code asks which program the first time, guesses the newest one in the build folders, and keeps it in .huginn-debug.

## Side by side and the minimap
Ctrl+\ shows two files side by side (click either to type in it; picking a tab swaps them). Long files get a minimap on the right: the whole file drawn small, with the part on screen marked. Click or drag on it to go there. Turn it off with "Toggle the Minimap" in the command list (Ctrl+Shift+P).

## Who changed this line (blame)
Ctrl+Alt+B shows, by every line, who last changed it, when and why; the line you're on shows it at its end in any case. Click it to see that whole change.

## History
The history of the folder, or of the file you're in, with the branches drawn as lines: click a change to see what it did, file by file.

## Tests
The Tests panel finds the project's tests (pytest, Go and Rust) and runs them all, a file, or one. Failures show what was expected and what came instead; click to go to the test. Ctrl+Shift+T runs them again.
