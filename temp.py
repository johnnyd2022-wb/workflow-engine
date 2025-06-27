def calculate_ethanol_to_add_using_alternate_formula(vol_of_wine, spirit_alc_concentration, desired_alc_concentration, current_alc_concentration):
    """
    Calculate the volume of spirits (ethanol) to add to a given volume of wine or spirits
    to achieve a desired ABV using Pearson's square formula.

    Parameters:
        vol_of_wine (float): The total volume of wine or spirits in milliliters.
        spirit_alc_concentration (float): The alcohol concentration of the spirits being added (as a percentage).
        desired_alc_concentration (float): The desired alcohol concentration after fortification (as a percentage).
        current_alc_concentration (float): The current alcohol concentration of the mixture (as a percentage).

    Returns:
        float: The volume of spirits (ethanol) to add in milliliters.
    """
    # Calculate the volume of spirits to add using Pearson's square formula
    volume_to_add = vol_of_wine * ((desired_alc_concentration - current_alc_concentration) / (spirit_alc_concentration - desired_alc_concentration))

    return volume_to_add

# Get user inputs
vol_of_wine = float(input("Enter the total volume of wine or spirits in milliliters: "))
spirit_alc_concentration = float(input("Enter the alcohol concentration of the spirits being added (as a percentage): "))
desired_alc_concentration = float(input("Enter the desired alcohol concentration after fortification (as a percentage): "))
current_alc_concentration = float(input("Enter the current alcohol concentration of the mixture (as a percentage): "))

# Calculate the volume of spirits to add using the adjusted formula
volume_to_add = calculate_ethanol_to_add_using_alternate_formula(vol_of_wine, spirit_alc_concentration, desired_alc_concentration, current_alc_concentration)

print(f"The volume of spirits to add is: {volume_to_add:.4f} mL")

