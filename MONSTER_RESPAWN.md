# Monster Respawn — Feasibility (timed re-arm of a monster gate, map-only)

Companion to `MONSTER_GATING.md`. Answers: **can placed guardian monsters RESPAWN
on a timer, map-only (no UnrealScript), ideally synced to the Redeemer pickup's
respawn?**

All claims below are cited to stock UnrealScript source. Source files were exported
with `UCC.exe batchexport <pkg>.u Class UC` into `C:\UT2004\System\` and the prior
export at `...\nostalgic-curie-d88d4b\uc_export\`.

---

## 0. TL;DR verdict

| Question | Answer |
|---|---|
| **Redeemer pickup respawn interval** | **120 seconds**, flat (no difficulty scaling). `RedeemerPickup.UC:80` + override `GetRespawnTime()` at `:20`. |
| **Can placed monsters respawn on a timer, map-only?** | **Not cleanly.** There is **NO stock placeable pawn factory/spawner** (no `Factory`, `SpawnPoint`, `MonsterSpawner`, `xPawnSpawner`, `RoamingMonster` in Engine). The *only* map-only way to spawn a pawn on a timer is a **`ScriptedTrigger` (ScriptedSequence) loop** using `ACTION_SpawnActor` + `ACTION_WaitForTimer` + `ACTION_GotoAction` — but it requires a surviving **host pawn** to drive it and is **unproven under DM**. Fragile, not recommended. |
| **Can the Counter+Mover gate re-arm each cycle?** | **The Counter CANNOT.** Once `NumToCount` hits 0 it latches permanently; `Counter.Reset()` only runs on full level restart, not on a re-trigger (`Counter.UC:32-35`, `:46`). The **Mover CAN auto re-lock** (`TriggerOpenTimed` closes after `StayOpenTime`, `Mover.UC:798`), but with a dead Counter there is nothing to re-open it. |
| **Sync respawn exactly to the Redeemer (120 s)?** | Achievable *as a number* (`ACTION_WaitForTimer PauseTime=120`) but not as a guaranteed phase-lock, and only via the fragile ScriptedTrigger path. |

**Bottom line:** A robust, code-free, periodically-self-rearming monster gate is
**not achievable with stock placeable actors.** The honest recommendation is the
**fallback** in §5 (one-shot gate, as `MONSTER_GATING.md` already designs; the
Redeemer behind it respawns on its own 120 s timer regardless). If timed respawn is
a hard requirement, it needs the small mutator already listed as fallback #4 in
`MONSTER_GATING.md`.

---

## 1. Pickup respawn timing — the interval to match

The respawn timer lives on the **Pickup** that the base spawns, not on the base.
`xWeaponBase` (`xWeaponBase.UC`) extends `xPickUpBase`, whose `PostBeginPlay()`
spawns `myPickUp` of class `PowerUp` (`xPickUpBase.UC:84`). `PowerUp` is set from
the weapon's `PickupClass` (`xWeaponBase.UC:32`).

- Redeemer's `PickupClass = XWeapons.RedeemerPickup` (`Redeemer.UC:92`).
- `RedeemerPickup` (`RedeemerPickup.UC`) sets **`RespawnTime=120.000000`** (`:80`)
  and **overrides `GetRespawnTime()` to return the raw `RespawnTime`** (`:20-22`) —
  so for the Redeemer there is **no GameDifficulty scaling** (the generic
  `WeaponPickup.GetRespawnTime()` would otherwise multiply by
  `0.33 + 0.22*GameDifficulty`, `WeaponPickup.UC:114`).
- The respawn loop is in `Pickup.UC` state `Sleeping`: after pickup it does
  `Sleep( GetReSpawnTime() - RespawnEffectTime )` then `RespawnEffect()` then
  re-enters `Pickup` (`Pickup.UC:417-424`).

**Super-weapon delayed-spawn detail (matters for the trophy):** the Redeemer's
`InventoryGroup==0` (`Redeemer.UC:90`) makes `xWeaponBase.PostBeginPlay()` set
`bDelayedSpawn=true` (`xWeaponBase.UC:33-34`), which puts the pickup into
`WaitingForMatch` → `Sleeping` 'DelayedSpawn' at match start (`xPickUpBase.UC:38-43`,
`Pickup.UC:368-416`). So the Redeemer is **not present at the start of a standalone
match for ~30 s** (`Sleep(FMin(30, GameDifficulty*8))`, `Pickup.UC:412-413`), then
respawns every **120 s** after each pickup. `bWeaponStay=True` is the DM default
(`DeathMatch.UC:1991`) but it governs *normal* weapons staying; the super weapon's
`bDelayedSpawn` path makes it respawn regardless.

> **Interval to match = 120.0 seconds.**

---

## 2. Map-only monster respawn — what exists and what does not

### 2.1 No stock pawn factory/spawner is placeable

Searched Engine, XGame, UnrealGame, Gameplay, SkaarjPack exports. The only
spawn-capable placeable actors are:

| Actor | Spawns | Configurable to a Monster? |
|---|---|---|
| `KVehicleFactory` / `SVehicleFactory` (Engine) | vehicles | No — vehicle classes only |
| `ProjectileSpawner` (Engine, `placeable`) | hardcoded `SpawnerProjectile` (`ProjectileSpawner.UC:43`) | **No** — class is hardcoded, not a `var()` |
| `xBombSpawn` (XGame) | Bombing-Run bomb | No |
| `InvasionPoint` (SkaarjPack) | wave monsters | only under the **Invasion** gametype |

There is **no** `Factory`, `SpawnPoint`, `MonsterSpawner`, `xPawnSpawner`, or
`RoamingMonster` class. The belief that a generic placeable monster spawner exists is
false for stock UT2004.

### 2.2 The one map-only spawn path: ScriptedTrigger + ACTION_SpawnActor (FRAGILE)

`ScriptedTrigger extends ScriptedSequence extends AIScript` and is **`placeable`**
(`ScriptedTrigger.UC:5`, `AIScript.UC:10`). It holds an editinline array
`Actions[]` of `ScriptedAction` objects (`ScriptedSequence.UC:8`) configured
entirely in editor properties — no UnrealScript subclass needed. The relevant
actions exist:

- **`ACTION_SpawnActor`** — spawns any `var() class<Actor> ActorClass` at
  `SequenceScript.Location + LocationOffset`, and sets the spawned actor's `Tag`
  (`ACTION_SpawnActor.UC:3-28`). So it *can* spawn `Warlord`/`Skaarj`, and the
  spawned monster self-possesses its own `MonsterController` (per
  `MONSTER_GATING.md` §1.2 — independent of how it was spawned).
- **`ACTION_WaitForTimer`** — latent wait of `var() float PauseTime`
  (`ACTION_WaitForTimer.UC`). Set `PauseTime=120` to match the Redeemer.
- **`ACTION_GotoAction`** — `C.ActionNum = ActionNumber` (`ACTION_GotoAction.UC:5-8`)
  → jump back to action 0 to loop forever.

So an actions list `[SpawnActor(Warlord), WaitForTimer(120), GotoAction(0)]` is, on
paper, a code-free 120 s monster spawner loop.

**Why this is fragile / unproven (be honest):**

1. **A ScriptedSequence does not run on its own — it must POSSESS a Pawn.** The script
   is driven by a `ScriptedController` that `TakeControlOf(P)` a pawn
   (`ScriptedSequence.UC:57-72`), and a pawn finds its script by matching
   `AIScriptTag` at startup (`Pawn.UC:115`, `:1936-1938`). So the loop needs a
   **persistent "host" pawn** that stays alive for the whole match. If the host is
   one of the guardians and it dies, its `ScriptedController` dies and the loop
   stops. You would need a *separate*, hidden, effectively-immortal host pawn
   (e.g. a high-health monster walled off out of reach, or a non-combat pawn) —
   itself awkward to place and keep alive under DM.
2. **Unproven under DM.** The scripted-AI system (Gameplay package) is built for
   single-player/Assault scripted sequences. Whether a `ScriptedTrigger` + host pawn
   reliably ticks and loops under `xDeathMatch` has **not** been observed in-engine
   here, and is exactly the same class of risk as the placed-monster question that
   `MONSTER_GATING.md` still flags as PENDING A HUMAN RUN. Layering an unproven
   scripted loop on top of an unproven monster-tick is high risk.
3. **Spawn-stacking.** The loop spawns unconditionally — it does not check whether
   the previous guardians are dead. After N cycles you accumulate monsters unless you
   also gate the spawn (no clean map-only "is the previous one dead?" test exists in
   the action set).

Verdict for §2: **placed monsters that are killed are gone permanently.** Only a
*newly spawned* monster (via the ScriptedTrigger loop) can appear — and that path is
fragile and unconfirmed. **Recommend against it.**

---

## 3. Re-arming the gate — the Counter is the hard blocker

Even if monsters respawned, the gate logic in `MONSTER_GATING.md` cannot re-lock
cyclically:

- **`Counter` latches permanently.** `Trigger()` only acts `if (NumToCount > 0)` and
  decrements toward 0 (`Counter.UC:46-48`). Once at 0 it ignores all further
  triggers. `Counter.Reset()` (which restores `NumToCount=OriginalNum`) is the engine
  **`Reset()` event fired only on a level reset/match restart** (`Counter.UC:29-35`),
  not something a Trigger/Dispatcher can invoke mid-match. **There is no map-only way
  to re-arm a Counter during a match.**
- **The Mover CAN auto re-lock.** `Mover` state `TriggerOpenTimed` (extends
  `OpenTimedMover`) opens on trigger and **auto-returns** after `StayOpenTime`
  (`Mover.UC:652-823`); `TriggerToggle`/`TriggerControl` (`:886`, `:936`) toggle on
  each trigger. So the *door* could be made to re-close on a timer. But with a dead
  Counter there is no actor left to re-open it on the next monster wave.

So the gate, as designed (Monster.Event → Counter → Mover), is **inherently
one-shot**. Re-arming would require replacing the Counter with something resettable,
and nothing stock fits map-only.

---

## 4. Concrete recipe

### 4.1 RECOMMENDED — one-shot gate; let only the Redeemer respawn (no monster respawn)

This is the `MONSTER_GATING.md` design unchanged. It is robust and code-free. The
**Redeemer behind the door respawns on its own 120 s timer** (§1) the moment a
player grabs it — so the *reward* re-arms automatically; only the *guardians* do not.
For "DM in a monster base," a one-time guardian kill that permanently opens a vault
whose trophy keeps respawning is a clean, shippable loop. No new actors needed beyond
the existing gate + this confirmation that the trophy self-respawns at 120 s.

### 4.2 BEST-EFFORT timed respawn (fragile, unconfirmed — use only if §4.1 rejected)

A `ScriptedTrigger` loop driven by a hidden immortal host pawn. **Spawns** new
guardians every 120 s; does **not** gate the spawn on the previous wave being dead,
and does **not** re-arm the Counter (so pair it with a self-re-locking
`TriggerToggle` Mover driven by a *separate* re-arm signal, which stock actors cannot
cleanly provide — hence "best-effort"). Paste-ready skeleton:

```
; --- the spawner script (placed where you want monsters to appear) ---
Begin Actor Class=ScriptedTrigger Name=GuardianSpawner
    Tag=GuardianSpawner
    ControllerClass=Class'Gameplay.ScriptedController'
    Location=(X=...,Y=...,Z=...)        ; spawn origin; monsters appear at Location+LocationOffset
    Begin Object Class=ACTION_SpawnActor Name=Act0
        ActorClass=Class'SkaarjPack.Warlord'
        LocationOffset=(Z=64)            ; lift flyers off the floor
        ActorTag=GuardianMon             ; spawned monster's Tag (wire to a Counter if used)
    End Object
    Begin Object Class=ACTION_WaitForTimer Name=Act1
        PauseTime=120.000000             ; == Redeemer RespawnTime
    End Object
    Begin Object Class=ACTION_GotoAction Name=Act2
        ActionNumber=0                   ; loop forever
    End Object
    Actions(0)=ACTION_SpawnActor'Act0'
    Actions(1)=ACTION_WaitForTimer'Act1'
    Actions(2)=ACTION_GotoAction'Act2'
End Actor

; --- host pawn that DRIVES the script (must survive the whole match) ---
; Place a Monster out-of-reach (sealed alcove) with high health, AIScriptTag matching the script.
Begin Actor Class=SkaarjPack.Skaarj Name=ScriptHost
    AIScriptTag=GuardianSpawner          ; binds this pawn to the ScriptedTrigger above
    Health=100000                        ; effectively immortal so the loop never stops
    Location=(X=...,Y=...,Z=...)         ; walled off, players cannot reach/kill it
End Actor
```

**Caveats restated:** (a) the host pawn must be unkillable and reachable by the AI
system but not by players; (b) whether this whole chain ticks under `xDeathMatch` is
UNCONFIRMED and must be human-tested exactly like the base monster-gating spike;
(c) spawned monsters accumulate — there is no clean map-only "only respawn if dead"
guard, and the Counter that opens the door cannot re-arm (§3), so the door will not
re-lock on subsequent waves. This recipe gives you *recurring monsters at the spawn
point*, not a faithfully *re-arming gate*.

### 4.3 Door auto re-lock (if you want the door itself to close on a timer)

Independent of monsters, swap the one-shot door for a timed one so it re-closes:

```
Begin Actor Class=Mover Name=VaultDoor
    InitialState=TriggerOpenTimed        ; opens on trigger, auto-closes after StayOpenTime
    StayOpenTime=120.000000              ; match the Redeemer cadence
    MoveTime=2.0
    bTriggerOnceOnly=False               ; allow repeated triggering
    Tag=VaultDoorTag
    ... KeyPos / mesh as in MONSTER_GATING.md §1.5 ...
End Actor
```

But note: re-closing the door is only meaningful if something re-opens it later, and
the Counter can't re-fire (§3). So this is useful only in the fragile §4.2 world.

---

## 5. Fallback / recommendation

**Ship the one-shot gate (§4.1).** It is the only robust, fully-confirmed,
truly-map-only option. The guardians are a one-time obstacle; the Redeemer trophy
behind the door respawns every **120 s** on its own, giving ongoing reward value
without any monster-respawn machinery.

If "guardians must periodically return" is a hard design requirement, the honest
answer is that **stock placeable actors cannot deliver a clean, re-arming, code-free
version of it.** The least-bad options, in order:

1. **§4.2 ScriptedTrigger loop** — map-only but fragile, unconfirmed under DM,
   spawn-stacking, and the gate Counter still won't re-arm. Human-test before trusting.
2. **Tiny mutator** (fallback #4 in `MONSTER_GATING.md`) — a few lines that, on a
   repeating timer, respawn the named guardians and reset the gate Counter. This is the
   smallest *reliable* path and the only one that can truly phase-lock to the Redeemer.
   It breaks the "no UnrealScript" lock — escalate to the user.

Do not silently adopt §4.2 as if it were proven; it carries the same (compounded)
in-engine risk that `MONSTER_GATING.md` still lists as pending a human run.

---

## Source index

- `C:\UT2004\System\xWeaponBase.UC` (:4 extends xPickUpBase, :32 PowerUp from PickupClass, :33-34 bDelayedSpawn)
- `C:\UT2004\System\xPickUpBase.UC` (:84 SpawnPickup, :38-43 delayed spawn → WaitingForMatch)
- `C:\UT2004\System\Redeemer.UC` (:90 InventoryGroup=0, :92 PickupClass=RedeemerPickup)
- `C:\UT2004\System\RedeemerPickup.UC` (:20-22 GetRespawnTime override, :80 RespawnTime=120)
- `C:\UT2004\System\WeaponPickup.UC` (:16-18 SetWeaponStay, :114 difficulty-scaled GetRespawnTime)
- `C:\UT2004\System\Pickup.UC` (:368-425 WaitingForMatch/Sleeping/Respawn states, :417-424 respawn loop)
- `...\uc_export\Counter.UC` (:32-35 Reset only on level reset, :46-48 latches at 0)
- `...\uc_export\Mover.UC` (:798 TriggerOpenTimed auto-close, :886 TriggerToggle, :936 TriggerControl, :825 LoopMove)
- `...\uc_export\ScriptedTrigger.UC` / `ScriptedSequence.UC` (:8 Actions array, :57-72 TakeOver possesses a pawn)
- `...\uc_export\AIScript.UC` (:8-10 placeable Keypoint) + `Pawn.UC` (:115, :1936 AIScriptTag binding)
- `...\uc_export\ACTION_SpawnActor.UC`, `ACTION_WaitForTimer.UC`, `ACTION_GotoAction.UC`
- `...\uc_export\ProjectileSpawner.UC` (:43 hardcoded SpawnerProjectile)
- `...\uc_export\DeathMatch.UC` (:1991 bWeaponStay=True default)
</content>
</invoke>
