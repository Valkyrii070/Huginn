# Huginn AI
Ask questions in Search, and rewrite, summarise and draft in Writer, Mail and Code. It's off until you turn it on in Settings › AI.

## Turn it on
Open Settings › AI, turn on Huginn AI, and choose where it runs: on this computer, or with an account you have with an AI service. Nothing is sent anywhere until both are done, and then only what you ask about, when you ask.

## On this computer
Choose a model and Download it, once (a few gigabytes, from Hugging Face). It runs through llama.cpp on the graphics card, or on the processor if there isn't one, and nothing you ask leaves the computer. Settings suggests the one that suits your computer: Small for 8 GB of memory, Balanced for 16 GB or a graphics card with 6 GB, Strong (gpt-oss 20B) for a graphics card with 16 GB. The model starts the first time you ask and stops after a quarter of an hour unused, which gives the graphics card's memory back. Turn off Use the graphics card to keep the card free for a game.

## With your account
Claude, OpenAI, Gemini, GitHub Models (the models behind Copilot), Azure OpenAI and OpenRouter each need a key from their developer site: Get a Key opens the page. Paste it in, and Settings lists the models the account offers, likeliest first. OpenRouter has Sign In instead: sign in on its page and its key comes back by itself.

A chat subscription (ChatGPT Plus, Claude Pro, Gemini Advanced, Copilot Pro) doesn't let other apps use it: each service sells that separately, as an API key, billed by use. Gemini's and GitHub's keys have free tiers.

## Another service
Anything that speaks OpenAI's API works too: Ollama (http://127.0.0.1:11434/v1), LM Studio, or a server of your own. Give its address, and a key if it needs one.

## Where keys are kept
In Passwords, under your master password, when Passwords is set up and unlocked; otherwise in a file only you can read. If the key is in Passwords and Passwords is locked, Huginn AI asks you to unlock it. Forget the key in Settings › AI, and revoke it on the service's own site if you're done with it.

## In Search
Type a question in Search everything (Super+Space), then Ctrl+Enter or choose Ask Huginn AI. The answer is written as it comes. Type a follow-up and Ctrl+Enter again; Escape goes back to the results.

## In Writer
The sparkle at the end of the formatting island: make it clearer, shorter, friendlier, more formal or simpler, proofread, summarise, or carry on writing. It works on what's selected, or on the whole document when nothing is. Nothing changes until you choose Replace or Insert, and Undo takes it back.

## In Mail
The sparkle beside Forward: summarise the message, or draft a reply (saying yes, no, or asking for time). Use It opens the reply with the draft in it. While writing, Improve makes what you've written clearer and keeps your signature and the quoted message as they are.

## In Code
In the command palette (Ctrl+Shift+P): AI: Explain This Code, Fix This Code (it's told about the problems Code found), Change This Code… and Write Code…. They work on what's selected, or the whole file. The code is shown first; Replace or Insert puts it in, and Undo takes it back.

## Turning it off here and there
Settings › AI › Where it shows turns it off for Search, Writer, Mail or Code on their own. Turning Huginn AI off hides it everywhere.
