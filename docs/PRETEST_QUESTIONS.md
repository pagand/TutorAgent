# Baseline Pretest (10 items)

Administered to **all** students before the main exam, before the A/B condition has any effect on them.
Its only job is to measure prior knowledge so that the `free_choice` and `adaptive` groups can be shown to be equivalent at baseline.

**Not** part of the graded exam, and not loaded into the adaptive engine.
Do not seed these into `prod/data/server_ready_questions.csv`.

---

## Design

| Property | Value |
|---|---|
| Items | 10, all multiple choice, 4 options, exactly one correct |
| Skills | `SGD-M`, `ADAM`, `REG`, `INIT`, `BN` - 2 items each |
| Difficulty | 4 easy, 4 medium, 2 hard |
| Source of knowledge | General deep-learning background. Nothing here requires the exam's lecture segments. |
| Overlap with exam | None. Same five skills, different concepts, no reused stems, options, or numbers. |
| Expected mean | ~5-7 / 10, with real spread. A pretest everyone aces or everyone fails cannot show group equivalence. |

Two items per skill is deliberate: it gives a per-skill subscore, so you can check equivalence on the whole test *and* on each skill, rather than letting a single skill imbalance hide inside a total.

### Coverage against the live exam bank

| Skill | Exam items (`prod/data/server_ready_questions.csv`) | Pretest items | Why they do not overlap |
|---|---|---|---|
| `SGD-M` | 1-5: large learning rate, mini-batch noise, momentum damping, velocity arithmetic, oscillation fix | 1, 2 | Tests the sign of the gradient step and epoch/batch bookkeeping. Momentum is never mentioned. |
| `ADAM` | 6-10: decay schedules, AdaGrad collapse, RMSprop EMA arithmetic, bias correction | 3, 4 | Tests which moments Adam tracks and what `beta2` controls. No schedule, no AdaGrad, no bias correction. |
| `REG` | 11-15: L1 sparsity geometry, L1 vs L2 near zero, weight decay, L2 gradient, decoupled decay | 5, 6 | Tests why a penalty exists at all and the large-lambda limit. Never contrasts L1 with L2. |
| `INIT` | 16-20: zero init, symmetry breaking, Xavier variance, He vs Xavier, vanishing gradients | 7, 8 | Tests bias initialization and forward activation scaling. Never names Xavier or He. |
| `BN` | 21-25: the transform, epsilon, running statistics, `model.eval()` | 9, 10 | Tests the practical payoff and the redundant bias. Never touches the formula, epsilon, or inference mode. |

Item 10 is the one to watch: it is the hardest of the medium band and most students will miss it.
That is intentional, it is what keeps the top of the distribution from saturating.

---

## Questions

### 1. `SGD-M` - easy

The gradient descent update is written as `w = w - eta * dL/dw`.
Why does the update *subtract* the gradient rather than add it?

- A. Because the learning rate `eta` is defined to be a negative number
- B. Because the gradient points in the direction of steepest *increase* of the loss, so moving opposite to it decreases the loss
- C. Because subtraction keeps the weights positive, which is required for backpropagation
- D. Because the loss function is always negative, so subtracting makes it larger

**Correct: B**
The gradient is the direction of steepest ascent; descent means stepping against it.

---

### 2. `SGD-M` - medium

You train on a dataset of 10,000 samples using mini-batch gradient descent with a batch size of 200, for 5 epochs.
How many parameter update steps does the optimizer perform in total?

- A. 50
- B. 250
- C. 2,000
- D. 50,000

**Correct: B**
10,000 / 200 = 50 updates per epoch, times 5 epochs = 250.
A is one epoch's worth; D is one update per sample per epoch, which is plain SGD, not mini-batch.

---

### 3. `ADAM` - easy

Which optimizer maintains a per-parameter adaptive step size using running estimates of **both** the first moment (mean) and the second moment (uncentered variance) of the gradient?

- A. Stochastic gradient descent with momentum
- B. AdaGrad
- C. Adam
- D. Vanilla gradient descent

**Correct: C**
SGD with momentum tracks only a first-moment-like velocity; AdaGrad accumulates only squared gradients; vanilla GD tracks neither.

---

### 4. `ADAM` - hard

In Adam, the second-moment estimate is updated as `v_t = beta2 * v_(t-1) + (1 - beta2) * g_t^2`.
If you raise `beta2` from its default 0.999 to 0.99999, what changes?

- A. The second-moment estimate averages over a much longer window of past gradients, so the per-parameter step sizes adapt more slowly to recent changes in gradient scale
- B. The step size decays monotonically to zero, reproducing AdaGrad's stalling behaviour exactly
- C. The update depends almost entirely on the most recent gradient, making training noisier
- D. Bias correction is no longer applied, because `beta2` is above the correction threshold

**Correct: A**
`beta2` is the retention factor of the exponential moving average; closer to 1 means longer memory and more sluggish adaptation.
C describes `beta2` near 0, the opposite direction.

---

### 5. `REG` - easy

What is the primary reason for adding a regularization penalty on the weights to the training objective?

- A. To make the optimizer converge in fewer epochs by enlarging the gradients
- B. To discourage overly large weights, so the model fits the training noise less and generalizes better
- C. To guarantee that the training loss eventually reaches exactly zero
- D. To remove the need for a separate validation set

**Correct: B**
Regularization trades a little training fit for lower variance and better generalization.

---

### 6. `REG` - medium

You train with an L2 penalty and keep increasing `lambda` to a very large value.
What do you expect to observe?

- A. Training error keeps falling while validation error rises, the classic overfitting signature
- B. The weights are driven toward zero, the model becomes too simple, and both training and validation error are high
- C. The weights grow without bound because the penalty dominates the loss gradient
- D. Nothing changes, because `lambda` only rescales the loss and not its minimizer

**Correct: B**
In the large-`lambda` limit the penalty dominates and the solution collapses toward the zero weight vector: underfitting, high bias.
A is the *small*-`lambda` failure mode.

---

### 7. `INIT` - medium

It is standard practice to initialize weights randomly but initialize all biases to zero.
Why is zero-initializing every bias in a layer acceptable, when zero-initializing every weight is not?

- A. Because bias terms do not receive gradients during backpropagation
- B. Because the randomly initialized weights already make each neuron compute a different function, so identical biases do not force identical behaviour
- C. Because biases are constants and are not learnable parameters
- D. Because a zero bias guarantees the ReLU units stay in their active region

**Correct: B**
Symmetry breaking is the weights' job. Once neurons differ, a shared constant offset does not collapse them back together.
Biases are learnable and do receive gradients, so A and C are simply false.

---

### 8. `INIT` - hard

You build a 30-layer fully connected ReLU network with 512 units per layer and initialize every weight from `N(0, 1)`, ignoring the layer width.
What happens to the activations as a forward pass propagates through the network?

- A. Their magnitudes grow roughly by a factor of the layer width at each layer, so they explode exponentially with depth and overflow to `inf` or `NaN`
- B. They shrink toward zero at each layer, so the deepest layers output all zeros
- C. They stay statistically stable, because a zero-mean distribution cannot change the scale of the signal
- D. They become identical across all neurons in a layer, because all weights share the same distribution

**Correct: A**
The variance of a layer's output is about `fan_in * Var(w)` times the input variance.
With `Var(w) = 1` and `fan_in = 512`, each layer multiplies the variance by roughly 512 (about 256 after ReLU zeroes half the units), which blows up within a few layers.
This is exactly what the width-aware initialization schemes are designed to prevent.

---

### 9. `BN` - easy

Which of the following is a well-established practical benefit of inserting Batch Normalization layers into a deep network?

- A. It lets you train with larger learning rates and makes training much less sensitive to the choice of initialization
- B. It reduces the number of trainable parameters in the network
- C. It removes the need for an optimizer, since the activations are normalized directly
- D. It guarantees the network cannot overfit the training set

**Correct: A**
BN's headline effects are faster, more stable training and tolerance of a wider range of learning rates and initializations.
It *adds* two parameters per feature, so B is backwards.

---

### 10. `BN` - medium

A linear layer with a bias term feeds directly into a Batch Normalization layer.
Why is that bias term redundant?

- A. Because Batch Normalization subtracts the mini-batch mean, which cancels any constant offset the bias added
- B. Because the bias gradient is always zero once a normalization layer follows it
- C. Because Batch Normalization overwrites the linear layer's parameters during the forward pass
- D. Because the bias is only used at inference time, and Batch Normalization is disabled at inference

**Correct: A**
A constant added to every sample shifts the mini-batch mean by the same constant, and the mean subtraction removes it.
This is why `bias=False` is the convention on layers followed by BN.

---

## Answer key

| Item | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 |
|---|---|---|---|---|---|---|---|---|---|---|
| Answer | B | B | C | A | B | B | B | A | A | A |
| Skill | SGD-M | SGD-M | ADAM | ADAM | REG | REG | INIT | INIT | BN | BN |
| Difficulty | easy | medium | easy | hard | easy | medium | medium | hard | easy | medium |

Score is out of 10, one point per item, no partial credit, no penalty for a wrong answer.
Per-skill subscores are out of 2.

---

## How to use this for the group-equivalence check

The pretest only supports the unbiasedness claim if it is administered cleanly.

1. **Run it before the exam window and before any hint condition is experienced.**
   The A/B group is assigned at `POST /users/` creation, so a student can already carry a group label; what matters is that no student has seen a hint yet when they take the pretest.
2. **Identical items, identical order, identical time limit for both groups.**
   No hints, no chat, no retries, no feedback between items. This is a measurement instrument, not a teaching moment.
3. **Record the score alongside the student's `ab_group`** so the two can be joined later.
4. **Report the comparison two ways.**
   Total score: group means, standard deviations, n, and a two-sample test - Welch's t-test, with Mann-Whitney U as the distribution-free fallback for small or skewed samples.
   Per skill: the five 0-2 subscores, so a skill-level imbalance cannot hide inside an equal total.
5. **State the result as a failure to detect a difference, not as proof of equality.**
   With cohort sizes in the tens, a non-significant p-value is weak evidence on its own. Report the effect size (Cohen's d) and its confidence interval next to it, so a reader can see how large a difference the study could still have missed.
6. **Use the pretest score as a covariate in the main analysis.**
   Even when the groups look balanced, conditioning the exam-score comparison on the pretest score (ANCOVA, or a regression with pretest as a control) absorbs prior-knowledge variance and tightens the estimate of the hint condition's effect. This is the strongest use of the data, stronger than the balance check alone.
