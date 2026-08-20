import torch

# Load the weights file directly
ckpt = torch.load("best.pt", map_location="cpu", weights_only=False)

# Extract the training metrics dictionary
metrics = ckpt.get("train_metrics", {})

if not metrics:
    print("No training metrics found in this file.")
else:
    print("--- Final Evaluation Metrics ---")
    for metric_name, value in metrics.items():
        # Some metrics might be stored as single values or lists of values per epoch.
        # This will print the final value.
        if isinstance(value, list) and len(value) > 0:
            print(f"{metric_name}: {value[-1]:.4f}")
        else:
            print(f"{metric_name}: {value}")