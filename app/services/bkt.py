# app/services/bkt.py
from app.utils.config import settings
from app.utils.logger import logger
from app.state_manager import get_bkt_mastery
from app.models.user import SkillMastery

class BKTService:
    def __init__(self, p_l0=settings.bkt_p_l0, p_t=settings.bkt_p_t,
                 p_g=settings.bkt_p_g, p_s=settings.bkt_p_s):
        self.p_l0 = p_l0 # Prior knowledge probability
        self.p_t = p_t   # Transition probability (learning rate)
        self.p_g = p_g   # Guess probability
        self.p_s = p_s   # Slip probability
        logger.info(f"BKTService initialized with params: L0={p_l0}, T={p_t}, G={p_g}, S={p_s}")

    def _calculate_posterior(self, prior_ln: float, is_correct: bool) -> float:
        """Calculates P(L_n | Correct) or P(L_n | Incorrect)."""
        if is_correct:
            # P(Correct | Ln) = (1 - P(S)); P(Correct | ~Ln) = P(G)
            prob_correct_given_ln = 1.0 - self.p_s
            prob_correct_given_not_ln = self.p_g
            # P(Correct) = P(Correct | Ln) * P(Ln) + P(Correct | ~Ln) * P(~Ln)
            prob_evidence = (prob_correct_given_ln * prior_ln) + \
                            (prob_correct_given_not_ln * (1.0 - prior_ln))
            if prob_evidence == 0: return prior_ln # Avoid division by zero
            # Bayes Theorem: P(Ln | Correct) = [P(Correct | Ln) * P(Ln)] / P(Correct)
            posterior = (prob_correct_given_ln * prior_ln) / prob_evidence
        else:
            # P(Incorrect | Ln) = P(S); P(Incorrect | ~Ln) = 1 - P(G)
            prob_incorrect_given_ln = self.p_s
            prob_incorrect_given_not_ln = 1.0 - self.p_g
             # P(Incorrect) = P(Incorrect | Ln) * P(Ln) + P(Incorrect | ~Ln) * P(~Ln)
            prob_evidence = (prob_incorrect_given_ln * prior_ln) + \
                            (prob_incorrect_given_not_ln * (1.0 - prior_ln))
            if prob_evidence == 0: return prior_ln # Avoid division by zero
            # Bayes Theorem: P(Ln | Incorrect) = [P(Incorrect | Ln) * P(Ln)] / P(Incorrect)
            posterior = (prob_incorrect_given_ln * prior_ln) / prob_evidence

        # Clamp probability between 0 and 1
        return max(0.0, min(1.0, posterior))

    def _calculate_mastery_update(self, prior_ln_minus_1: float, is_correct: bool) -> float:
        """
        Calculates the new mastery probability without committing it.
        This allows us to preview the change for feedback calculation.
        """
        # 1. Calculate posterior based on evidence P(L_{n-1} | evidence)
        posterior_ln_minus_1 = self._calculate_posterior(prior_ln_minus_1, is_correct)

        # 2. Apply transition (learning) P(L_n) = P(L_{n-1} | evidence) + (1 - P(L_{n-1} | evidence)) * P(T)
        new_ln = posterior_ln_minus_1 + (1.0 - posterior_ln_minus_1) * self.p_t
        return max(0.0, min(1.0, new_ln))

    async def update_mastery(self, user_id: str, skill: str, is_correct: bool, existing_skill_mastery: SkillMastery) -> float:
        """
        Updates the mastery probability for a user and skill using an existing SkillMastery object.
        This is more efficient as it avoids a separate DB query.
        """
        # 1. Get prior mastery P(L_{n-1}) directly from the passed object
        prior_ln_minus_1 = existing_skill_mastery.mastery_level

        # 2. Calculate the new mastery level
        new_ln = self._calculate_mastery_update(prior_ln_minus_1, is_correct)

        # 3. Update the mastery on the existing object
        existing_skill_mastery.mastery_level = new_ln
        
        logger.debug(f"BKT Update: User={user_id}, Skill={skill}, Correct={is_correct}, Prior={prior_ln_minus_1:.4f}, New P(L)={new_ln:.4f}")
        
        return new_ln

    async def predict_correct_probability(self, user_id: str, skill: str) -> float:
        """Predicts the probability the user will answer the NEXT question on this skill correctly."""
        # P(Correct_next | L_n) = P(L_n) * (1 - P(S)) + (1 - P(L_n)) * P(G)
        # This still requires a query if we don't have the object, which is fine for this separate function.
        current_mastery = await get_bkt_mastery(user_id, skill, self.p_l0)
        prob_correct = (current_mastery * (1.0 - self.p_s)) + \
                       ((1.0 - current_mastery) * self.p_g)
        return prob_correct

# Instantiate the BKT service
bkt_service = BKTService()
