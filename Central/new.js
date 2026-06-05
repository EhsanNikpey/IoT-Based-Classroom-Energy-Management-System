if (data.efficiency) {
    document.getElementById('energy-score').textContent = data.efficiency + '%';
    document.getElementById('energy-progress').style.width = data.efficiency + '%';
}