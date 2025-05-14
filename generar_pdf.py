from weasyprint import HTML, CSS

# HTML con estilos y tabla
html_string = """
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <style>
    body {
      font-family: sans-serif;
      margin: 2cm;
    }

    h1 {
      text-align: center;
      color: #003366;
    }

    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 12px;
    }

    th, td {
      border: 1px solid #ccc;
      padding: 8px;
      text-align: left;
      word-wrap: break-word;
    }

    th {
      background-color: #00aaff;
      color: white;
    }

    td {
      max-width: 120px;
    }
  </style>
</head>
<body>
  <h1>Horarios Generados</h1>
  <table>
    <tr>
      <th>Día</th>
      <th>Hora Inicio</th>
      <th>Hora Fin</th>
      <th>Asignatura</th>
      <th>Docente</th>
      <th>Aula</th>
      <th>Jornada</th>
    </tr>
    <tr>
      <td>Lunes</td>
      <td>07:30</td>
      <td>10:30</td>
      <td>Programación 2</td>
      <td>Edgar</td>
      <td>Sala 8</td>
      <td>Mañana</td>
    </tr>
    <!-- Puedes seguir agregando más filas si quieres -->
  </table>
</body>
</html>
"""

# Generar el PDF
HTML(string=html_string).write_pdf(
    "prueba.pdf",
    stylesheets=[CSS(string='@page { size: A4 landscape; margin: 2cm; }')]
)

print("✅ PDF generado como 'prueba.pdf'")
