# Code Philosophy

This document defines the code philosophy for JJZero Audio.

The core rule is simple:

> The call site should express intent in one line, the owner of that feature should close over validation, branching, and execution internally, and when a bug appears we should be able to follow the feature name to one place and fix it there.

## Why This Exists

This project combines Qt UI, workspace state, file management, audio pipelines, and external runtimes.
If responsibility leaks across those areas, the code becomes difficult to trace, debug, and change safely.

We optimize for:

- short call paths
- obvious ownership
- one-stop debugging
- minimal structural overhead

We do not optimize for:

- adding classes for the sake of object orientation
- removing every `if` regardless of ownership
- deduplicating code when it makes ownership less clear

## Core Principles

### 1. Callers Speak Only in Intent

Call sites should say what they want, not how the feature works internally.

Good:

```python
song_library.remove_asset(song_id, asset_path)
processing_queue.fail(task_id, error_text)
separation_recipe.describe()
```

Bad:

- the caller checks half of the preconditions first
- the caller decides which branch of the feature is valid
- the caller reimplements fallback behavior before invoking the owner

If a caller must know policy details to use a feature safely, the responsibility boundary is wrong.

### 2. The Feature Owner Holds the Full Responsibility

The object or module that owns a feature must own its full rule set.

Examples:

- song library owns song indexing, package lookup, and asset removal entry points
- RVC runtime services own runtime selection, activation, and compatibility checks
- separation recipe logic owns recipe description, selection rules, and asset requirements
- processing queue owns task lifecycle state transitions

The owner should not force UI code or neighboring services to reconstruct its rules.

### 3. One Bug Should Lead to One Place

When a feature breaks, we should be able to follow its name to one primary implementation area.

Good:

- separation recipe bug -> `services/separation_recipe.py`
- song removal bug -> `services/song_asset_removal.py` or `services/song_library.py`
- RVC profile activation bug -> `services/rvc_profile_activation.py`

Bad:

- one rule partially in `main_window.py`
- another branch in a widget
- fallback logic copied into a worker
- path correction repeated in a pipeline adapter

If fixing one bug requires searching many unrelated modules, the responsibility has leaked.

### 4. Object Orientation Is Not About Increasing Object Count

Adding `Manager`, `Processor`, `Context`, `Registry`, or `Helper` classes does not automatically improve structure.

A new abstraction is justified only when it:

- gives a feature one clear owner
- shortens the call path
- removes duplicated policy logic
- improves testability without hiding behavior

If an abstraction only forwards calls, stores loose references, or hides a simple rule behind indirection, it is probably a bad abstraction.

### 5. Use Polymorphism Only to Remove Central Type Branching

Polymorphism is useful when new types would otherwise keep expanding a central `if` or `match`.

Use it when:

- behavior truly varies by type
- the type-specific behavior naturally belongs to the object itself

Do not use it when:

- a single local branch is simpler and clearer
- the hierarchy exists only to avoid one small conditional
- the resulting navigation path becomes longer than the original code

Central branching is not the enemy by itself.
Misplaced central branching is the problem.

### 6. Policy Branches Must Live with Their Owner

Conditionals are normal.
What matters is where they live.

Examples:

- item-use policy belongs to the item or its owning feature
- stack mutation policy belongs to the stack action owner
- export naming policy belongs to export naming services
- runtime fallback policy belongs to runtime services

The wrong fix for a visible `if` is often adding another wrapper.
The right fix is moving that `if` into the real owner.

### 7. Unused Features Should Behave as If They Do Not Exist

Optional systems must not leak cost or responsibility into unrelated flows.

Examples:

- no Google Drive connection -> local export and library features should not care
- no studio video source -> audio workflows should not pay extra coordination cost
- no optional addon-like behavior -> base feature should stay small and direct

Optional capability should attach cleanly and disappear cleanly.

### 8. Responsibility Boundaries Matter More Than Deduplication

We do not extract shared code just because two blocks look similar.

We extract shared behavior only when the result:

- keeps ownership clearer
- reduces duplicated policy
- shortens debugging paths
- avoids nullable, half-valid parameter sets

Do not create broad shared contexts or generic entry points if they force unrelated rules into the same API.

## Python Translation

This philosophy applies to Python directly, but not every feature owner needs to be a class.

Use a class when the feature has:

- persistent state
- lifecycle
- subscriptions or listeners
- ownership over mutable data

Use module-level functions when the feature is:

- stateless
- rule-oriented
- a pure transformation
- easier to read without object ceremony

Examples:

- `ProcessingQueue` should stay an object because it owns evolving task state
- file naming helpers can remain functions if they are pure and tightly scoped
- a service module may be the owner of a feature even when it does not expose a class

The real rule is not "everything must be an object."
The real rule is "the feature owner must be obvious."

## Project-Level Mapping

In this repository, the ownership model should look like this:

- `qt_app/`
  - owns layout, widgets, user input wiring, and presentation state
  - should request behavior, not reimplement domain rules
- `services/`
  - owns domain logic, storage rules, runtime decisions, naming, and workflow state
  - should be the first place to inspect for feature bugs
- `pipeline/`
  - owns execution adapters for external audio engines and conversion tools
  - should not absorb UI policy or broad application state
- `scripts/`
  - owns development, benchmark, packaging, and maintenance entry points
  - should not become the canonical home of product logic

## Practical Rules for JJZero Audio

### Main Window

`main_window.py` is allowed to orchestrate screens, but it should not become the owner of feature policy.

That means:

- it may choose when to call a feature
- it may bind widget events to feature calls
- it should not hold the canonical branching logic for separation, conversion, export, or runtime activation

If a workflow rule grows complicated enough that it needs comments or repeated prechecks in the window, that rule likely belongs elsewhere.

### Services

Service modules should be feature owners, not dumping grounds.

Good service modules:

- have a narrow feature name
- expose a small number of intent-revealing entry points
- keep related rule branches together

Bad service modules:

- collect unrelated helpers
- hide behavior behind generic names
- require callers to assemble half-valid context objects first

### UI Modules

Widgets and panels may keep presentation-local state, but they should not become secret domain controllers.

UI code should not:

- recreate path selection rules
- duplicate export naming logic
- decide runtime compatibility independently
- hold authoritative removal or recovery policies

### Naming Rules

Prefer names that describe ownership directly.

Good:

- `SongLibrary`
- `SongAssetRemovalService`
- `RvcProfileActivation`
- `SeparationRecipe`

Avoid vague names unless the object is truly generic infrastructure:

- `Manager`
- `Processor`
- `Context`
- `Registry`
- `Helper`
- `Util`

If the name does not tell us what bug it should own, the boundary is probably too weak.

## Review Checklist

Before adding or changing logic, ask:

1. Does the caller express only intent?
2. Does one feature owner hold validation, branching, and execution?
3. If this breaks, will I know which file to open first?
4. Did I add a new abstraction because it clarifies ownership, or only because the code looked large?
5. Did I move policy to the owner, or merely move code elsewhere?
6. Did I preserve optional features as optional, without leaking their cost?
7. Did I avoid fake deduplication that weakens the boundary?

If several answers are "no," the design is not finished.

## Non-Goals

This philosophy does not require:

- class-heavy architecture
- zero conditionals
- framework-style dependency containers
- maximum deduplication
- generic reusable layers for hypothetical future features

It requires the minimum structure needed for clear ownership and short debugging paths.

## Final Standard

We consider a design healthy when:

- the call site is short and obvious
- the feature owner closes over the real behavior
- optional systems stay out of unrelated paths
- one bug leads to one place
- unnecessary structure is absent

That is the standard of "complete but not bloated" that this project should follow.
